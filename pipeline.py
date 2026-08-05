"""
pipeline.py — Tang multi-agent cua he thong K4 Day 09.

core.py giu phan tat dinh (KHONG duoc sai).
File nay giu phan agent: phan cong, handoff co cau truc, kiem chung cheo.

Nguyen tac phan vai:
  - So lieu  -> tool tat dinh trong core.py. LLM khong bao gio tu tinh.
  - Dieu phoi, phat hien fact thieu/mau thuan, kiem chung -> LLM <=10B.

Quyen truy cap du lieu duoc CUONG CHE o tang code: moi agent chi nhan dung
nhom tool cua minh. Coordinator va PolicyAgent khong nhan tool du lieu nao —
chung chi thay nhung gi cac specialist ban giao qua Handoff.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from core import (
    Assembler,
    CustomerTools,
    DataStore,
    DeliveryTools,
    EvidenceBundle,
    GateFailure,
    OrderProductTools,
    PaymentTools,
    PolicyDecision,
    PolicyEngine,
    ROOT_CAUSE_OF,
    Verifier,
    compute_confidence,
    money,
)

# ---------------------------------------------------------------------------
# MODEL REGISTRY
#
# Ten model khai bao CUNG trong source code (README §9.4: khong dat trong .env).
# Doi profile = doi mot dong ACTIVE_PROFILE.
#
# Rang buoc de bai: moi agent dung model <= 10B tham so. Gioi han theo TUNG
# model, khong cong don.
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env": "OPENAI_API_KEY",
    },
    "gemini": {
        # Google phuc vu endpoint tuong thich OpenAI -> dung chung mot SDK.
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env": "GEMINI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
    },
}

# Nguon goc con so tham so — ghi trung thuc vao metadata.json.
_EST_OPENAI = ("Abacha et al., 'MEDEC', Microsoft Research (2024-12) — UOC TINH "
               "cua ben thu ba; OpenAI chua bao gio xac nhan")
_UNDISCLOSED = "Nha cung cap KHONG cong bo so tham so"

_OPENAI_MINI = {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "parameter_size": "~8B (uoc tinh, chua duoc xac nhan)",
    "source_of_parameter_count": _EST_OPENAI,
}
# Bac nho hon cua OpenAI va thuoc THE HE KHAC (4.1 thay vi 4o).
_OPENAI_NANO = {
    "provider": "openai",
    "model": "gpt-4.1-nano",
    "parameter_size": "khong cong bo (bac nho nhat cua OpenAI)",
    "source_of_parameter_count": _UNDISCLOSED,
}
_GEMINI_LITE = {
    "provider": "gemini",
    "model": "gemini-2.5-flash-lite",
    "parameter_size": "khong cong bo",
    "source_of_parameter_count": _UNDISCLOSED,
}

MODEL_PROFILES: dict[str, dict[str, dict[str, str]]] = {
    # ---- Profile dang dung -----------------------------------------------
    # Chi OpenAI (key Gemini het credit tra truoc -> 429 tren moi lenh sinh).
    #
    # Verifier va Customer dung gpt-4.1-nano, KHAC THE HE voi gpt-4o-mini cua
    # Policy. Khong tach biet bang khac hang nhu thiet ke ban dau, nhung khac
    # lan huan luyen nen loi bot tuong quan hon la dung y het mot model —
    # neu Verifier trung model voi Policy, no se mac cung loai loi va cho qua
    # dung sai lam can bat.
    "openai_mixed_tier": {
        "coordinator": _OPENAI_MINI,
        "customer": _OPENAI_NANO,
        "order_product": _OPENAI_MINI,
        "payment": _OPENAI_MINI,
        "delivery": _OPENAI_MINI,
        "policy": _OPENAI_MINI,
        "verifier": _OPENAI_NANO,      # <- khac the he voi policy
    },

    # ---- Mot model duy nhat cho moi agent --------------------------------
    "openai_only": {
        role: _OPENAI_MINI
        for role in ("coordinator", "customer", "order_product", "payment",
                     "delivery", "policy", "verifier")
    },

    # ---- Ket hop OpenAI + Gemini -----------------------------------------
    # Dung duoc NGAY KHI key Gemini duoc nap credit. Day la phuong an tot nhat
    # ve mat kiem chung cheo: Verifier khac HANG voi Policy.
    "openai_gemini_mixed": {
        "coordinator": _OPENAI_MINI,
        "customer": _GEMINI_LITE,
        "order_product": _OPENAI_MINI,
        "payment": _OPENAI_MINI,
        "delivery": _OPENAI_MINI,
        "policy": _OPENAI_MINI,
        "verifier": _GEMINI_LITE,
    },

    # ---- Open-weights: profile DUY NHAT chung minh duoc rang buoc <=10B --
    #
    # Rang buoc de bai la <=10B cho TUNG MODEL, khong cong don. Bay agent dung
    # bay model 4B-9B la hop le; tong so tham so cua he thong khong lien quan.
    #
    # Tat ca deu la model DENSE. Da co y loai cac model MoE tren OpenRouter
    # (qwen3-30b-a3b, gemma-4-26b-a4b, qwen3-next-80b-a3b...): con so 'a3b'/
    # 'a4b' la tham so KICH HOAT moi token, tong tham so van 26-80B nen vi pham.
    #
    # Moi slug duoi day da duoc goi thu that va deu tra ve JSON hop le.
    "openrouter_open_weights": {
        "coordinator":   {"provider": "openrouter",
                          "model": "meta-llama/llama-3.1-8b-instruct",
                          "parameter_size": "8.0B (dense)",
                          "source_of_parameter_count": "Llama 3.1 model card (chinh thuc)"},
        "customer":      {"provider": "openrouter",
                          "model": "google/gemma-3-4b-it",
                          "parameter_size": "4.0B (dense)",
                          "source_of_parameter_count": "Gemma 3 model card (chinh thuc)"},
        "order_product": {"provider": "openrouter",
                          "model": "qwen/qwen-2.5-7b-instruct",
                          "parameter_size": "7.0B (dense)",
                          "source_of_parameter_count": "Qwen2.5 model card (chinh thuc)"},
        "payment":       {"provider": "openrouter",
                          "model": "meta-llama/llama-3.1-8b-instruct",
                          "parameter_size": "8.0B (dense)",
                          "source_of_parameter_count": "Llama 3.1 model card (chinh thuc)"},
        "delivery":      {"provider": "openrouter",
                          "model": "qwen/qwen-2.5-7b-instruct",
                          "parameter_size": "7.0B (dense)",
                          "source_of_parameter_count": "Qwen2.5 model card (chinh thuc)"},
        # Quyet dinh quan trong nhat. Da thu qwen3.5-9b nhung do tre ~8s/call
        # lam treo lot chay 50 case -> doi sang Granite 4.1 8B (do duoc ~0,9s).
        "policy":        {"provider": "openrouter",
                          "model": "ibm-granite/granite-4.1-8b",
                          "parameter_size": "8.0B (dense)",
                          "source_of_parameter_count": "Granite 4.1 model card (chinh thuc)"},
        # KHAC HANG voi policy (Mistral vs Qwen): neu trung model, verifier se
        # mac cung loai loi va cho qua dung sai lam can bat.
        "verifier":      {"provider": "openrouter",
                          "model": "mistralai/ministral-8b-2512",
                          "parameter_size": "8.0B (dense)",
                          "source_of_parameter_count": "Ministral 8B model card (chinh thuc)"},
    },
}

# Doi profile = doi DUNG MOT dong nay.
ACTIVE_PROFILE = "openrouter_open_weights"


def active_models() -> dict[str, dict[str, str]]:
    return MODEL_PROFILES[ACTIVE_PROFILE]


def required_env_keys() -> list[str]:
    """Cac bien moi truong ma profile dang chon can co."""
    providers = {spec["provider"] for spec in active_models().values()}
    return sorted(PROVIDERS[p]["env"] for p in providers)


# ---------------------------------------------------------------------------
# Handoff — hop dong giao tiep duy nhat giua cac agent
# ---------------------------------------------------------------------------

@dataclass
class Fact:
    key: str
    value: Any
    source_id: str          # BAT BUOC, phai dung duoc tu CSV


@dataclass
class Handoff:
    case_id: str
    question: str           # (1) cau hoi can tra loi
    from_agent: str
    to_agent: str
    facts: list[Fact] = field(default_factory=list)          # (2) fact + ID nguon
    missing_or_conflicting: list[str] = field(default_factory=list)  # (3)
    suggested_next: str = ""                                  # (4)
    ts: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "from": self.from_agent,
            "to": self.to_agent,
            "facts": [asdict(f) for f in self.facts],
            "missing_or_conflicting": self.missing_or_conflicting,
            "suggested_next": self.suggested_next,
            "ts": self.ts,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """Ghi logging/trace.jsonl.

    mode='w' cho lot chay day du 50 case (de bai: 'khong append, chi can lot
    chay moi nhat'); mode='a' khi chay lai mot case le de khong xoa trace cua
    49 case kia.
    """

    def __init__(self, path: str | Path, mode: str = "w") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open(mode, encoding="utf-8")
        # Cac case chay song song -> moi ghi vao trace deu phai qua lock,
        # neu khong cac dong JSON se dan xen vao nhau va file hong.
        self._lock = threading.Lock()
        self.counters: dict[str, int] = {
            "llm_calls": 0, "llm_failures": 0,
            "policy_discrepancies": 0, "gate_failures": 0, "retries": 0,
        }

    def _write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            self._fh.write(line)
            self._fh.flush()

    def emit(self, case_id: str, event: str, **payload: Any) -> None:
        record = {"ts": _now(), "case_id": case_id, "event": event}
        record.update(_jsonable(payload))
        self._write(record)

    def handoff(self, h: Handoff) -> None:
        h.ts = _now()
        record = {"ts": h.ts, "case_id": h.case_id, "event": "handoff"}
        record.update(_jsonable(h.to_json()))
        self._write(record)

    def bump(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + n

    def close(self) -> None:
        with self._lock:
            self._fh.close()


# ---------------------------------------------------------------------------
# LLM client — OpenAI-compatible, tuy chon
# ---------------------------------------------------------------------------

class LLMClient:
    """Bao mong quanh SDK OpenAI-compatible.

    Moi loi deu nuot va tra None -> agent roi ve nhanh tat dinh. Pipeline
    KHONG BAO GIO dung vi LLM.
    """

    # Timeout ngan + it retry: mot provider treo phai that bai NHANH roi roi ve
    # nhanh tat dinh, thay vi keo dai ca lot chay 50 case.
    def __init__(self, enabled: bool, tracer: Tracer | None = None,
                 timeout: float = 20.0) -> None:
        self.tracer = tracer
        self.timeout = timeout
        self.enabled = False
        self.missing_keys: list[str] = []
        self._clients: dict[str, Any] = {}     # provider -> OpenAI client
        if not enabled:
            return
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            self.missing_keys = ["<chua cai goi 'openai'>"]
            return

        # Mot profile co the dung nhieu provider (vd. policy o OpenAI,
        # verifier o Gemini). Dung client rieng cho tung provider.
        for provider in {spec["provider"] for spec in active_models().values()}:
            cfg = PROVIDERS[provider]
            api_key = os.environ.get(cfg["env"])
            if not api_key:
                self.missing_keys.append(cfg["env"])
                continue
            self._clients[provider] = OpenAI(
                api_key=api_key, base_url=cfg["base_url"], timeout=timeout,
            )
        self.missing_keys.sort()
        self.enabled = bool(self._clients)

    def available_for(self, agent: str) -> bool:
        return active_models()[agent]["provider"] in self._clients

    def chat_json(self, case_id: str, agent: str, system: str, user: str,
                  retries: int = 1) -> dict[str, Any] | None:
        spec = active_models()[agent]
        client = self._clients.get(spec["provider"])
        if not self.enabled or client is None:
            return None
        model = spec["model"]
        for attempt in range(retries + 1):
            started = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content or ""
                parsed = json.loads(content)
                if self.tracer:
                    self.tracer.bump("llm_calls")
                    usage = getattr(resp, "usage", None)
                    self.tracer.emit(
                        case_id, "llm_call", agent=agent, model=model,
                        provider=spec["provider"],
                        latency_ms=int((time.time() - started) * 1000),
                        prompt_tokens=getattr(usage, "prompt_tokens", None),
                        completion_tokens=getattr(usage, "completion_tokens", None),
                    )
                return parsed if isinstance(parsed, dict) else None
            except Exception as exc:  # noqa: BLE001 — LLM khong duoc lam sap pipeline
                if self.tracer:
                    self.tracer.bump("llm_calls")
                    self.tracer.emit(
                        case_id, "llm_error", agent=agent, model=model,
                        provider=spec["provider"], attempt=attempt,
                        error=type(exc).__name__, detail=str(exc)[:200],
                    )
                if attempt == retries:
                    if self.tracer:
                        self.tracer.bump("llm_failures")
                    return None
                time.sleep(1.5 * (attempt + 1))
        return None


# ---------------------------------------------------------------------------
# Case input
# ---------------------------------------------------------------------------

@dataclass
class CaseInput:
    case_id: str
    claimed_order_id: str
    language: str = "vi"
    message: str = ""
    include_customer_history: bool = True
    include_product_context: bool = True
    policy_version: str = "EC_POLICY_V2"

    @staticmethod
    def from_json(payload: dict[str, Any]) -> "CaseInput":
        req = payload.get("customer_request", {}) or {}
        scope = payload.get("investigation_scope", {}) or {}
        return CaseInput(
            case_id=payload.get("case_id", ""),
            claimed_order_id=req.get("claimed_order_id", ""),
            language=req.get("language", "vi"),
            message=req.get("message", ""),
            include_customer_history=bool(scope.get("include_customer_history", True)),
            include_product_context=bool(scope.get("include_product_context", True)),
            policy_version=payload.get("policy_version", "EC_POLICY_V2"),
        )


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class BaseAgent:
    name = "base"

    def __init__(self, llm: LLMClient, tracer: Tracer) -> None:
        self.llm = llm
        self.tracer = tracer

    def _annotate(self, case_id: str, facts: list[Fact],
                  question: str, context: str) -> tuple[list[str], str]:
        """Nho LLM chi ra fact thieu/mau thuan va de xuat buoc tiep theo.

        LLM KHONG duoc sua value cua fact — chi binh luan. Loi -> fallback tat dinh.
        """
        fallback_missing = [
            f.key for f in facts
            if f.value is None or (isinstance(f.value, list) and not f.value)
        ]
        fallback_next = "Chuyen evidence cho Policy Agent de ap EC_POLICY_V2."

        result = self.llm.chat_json(
            case_id, self.name,
            system=(
                "Ban la mot agent dieu tra khieu nai thuong mai dien tu. Ban NHAN "
                "cac fact da duoc trich tu du lieu goc; ban KHONG duoc thay doi "
                "gia tri cua chung.\n"
                "Nhiem vu: (a) liet ke fact con thieu hoac mau thuan, "
                "(b) de xuat buoc tiep theo cho agent nhan viec.\n"
                "QUY TAC cho (a) — rat quan trong:\n"
                "- CHI liet ke fact co trong danh sach duoi day ma gia tri la null "
                "hoac mang rong, HOAC hai fact mau thuan truc tiep voi nhau.\n"
                "- KHONG duoc suy dien, KHONG duoc doi hoi du lieu ngoai pham vi "
                "cong viec cua ban, KHONG duoc coi mot gia tri hop le la 'thieu'.\n"
                "- Trong du lieu Olist, order khong co item row va order chua giao "
                "deu la truong hop HOP LE, khong phai loi du lieu.\n"
                "- Neu moi fact deu day du: tra ve mang RONG.\n"
                'Tra ve JSON: {"missing_or_conflicting": [string], "suggested_next": string}'
            ),
            user=f"Cau hoi: {question}\n\nBoi canh: {context}\n\nFacts:\n"
                 + json.dumps([asdict(f) for f in facts],
                              ensure_ascii=False, default=str, indent=2),
        )
        if not result:
            return fallback_missing, fallback_next
        missing = result.get("missing_or_conflicting")
        nxt = result.get("suggested_next")
        return (
            [str(m) for m in missing] if isinstance(missing, list) else fallback_missing,
            str(nxt) if isinstance(nxt, str) and nxt else fallback_next,
        )


class CoordinatorAgent(BaseAgent):
    """Nhan case, lap plan, dispatch, gop ket qua. KHONG doc CSV."""

    name = "coordinator"

    DEFAULT_QUESTIONS = {
        "customer": "Khach hang nao dung sau order nay va ho tung mua gi truoc do?",
        "order_product": "Order gom nhung item, seller, product va category nao?",
        "payment": "Tong payment co khop tong item + freight khong?",
        "delivery": "Order giao dung han khong, va seller co ban giao tre khong?",
    }

    def plan(self, case: CaseInput,
             failed_gates: list[GateFailure] | None = None) -> dict[str, Any]:
        # Ca 4 specialist LUON chay: secondary issue (repeat_customer,
        # multiple_categories) duoc dinh nghia thuan tuy theo du lieu, khong
        # phu thuoc investigation_scope. Scope chi chan o khau xuat.
        agents = ["customer", "order_product", "payment", "delivery"]
        questions = dict(self.DEFAULT_QUESTIONS)
        rationale = "Plan mac dinh theo investigation_scope."

        result = self.llm.chat_json(
            case.case_id, "coordinator",
            system=(
                "Ban la Coordinator cua he thong dieu tra khieu nai e-commerce. "
                "Dua tren investigation_scope, quyet dinh nhung agent chuyen trach "
                "nao can duoc giao viec va cau hoi cu the cho tung agent. "
                "Agent kha dung: customer, order_product, payment, delivery. "
                "Tra ve JSON: "
                '{"agents": [string], "questions": {agent: string}, "rationale": string}'
            ),
            user=json.dumps(
                {
                    "case_id": case.case_id,
                    "message": case.message,
                    "include_customer_history": case.include_customer_history,
                    "include_product_context": case.include_product_context,
                    "previously_failed_gates": [g.code for g in (failed_gates or [])],
                },
                ensure_ascii=False,
            ),
        )
        if result:
            proposed = result.get("agents")
            if isinstance(proposed, list) and proposed:
                # LLM duoc quyet dinh THU TU uu tien dieu tra; nhung ca 4 agent
                # deu bat buoc co mat vi output can du 4 domain.
                allowed = ["customer", "order_product", "payment", "delivery"]
                picked = [a for a in proposed if a in allowed]
                picked += [a for a in allowed if a not in picked]
                agents = picked
            if isinstance(result.get("questions"), dict):
                for k, v in result["questions"].items():
                    if k in questions and isinstance(v, str) and v.strip():
                        questions[k] = v.strip()
            if isinstance(result.get("rationale"), str):
                rationale = result["rationale"]

        plan = {"agents": agents, "questions": questions, "rationale": rationale}
        self.tracer.emit(case.case_id, "plan", **plan)
        return plan


class CustomerAgent(BaseAgent):
    """Scope: customers, orders(order_id, customer_id)."""

    name = "customer"

    def __init__(self, llm: LLMClient, tracer: Tracer, tools: CustomerTools) -> None:
        super().__init__(llm, tracer)
        self.tools = tools

    def run(self, case: CaseInput, question: str) -> tuple[Any, Handoff]:
        # Luon tinh du lich su: 'repeat_customer' la dieu kien du lieu, khong
        # phu thuoc scope. Scope chi chan o khau xuat (Assembler).
        facts_obj = self.tools.resolve(case.claimed_order_id, include_history=True)
        src = f"order:{case.claimed_order_id}"
        facts = [
            Fact("customer_unique_id", facts_obj.customer_unique_id, src),
            Fact("related_order_ids", facts_obj.related_order_ids, src),
            Fact("is_repeat_customer", bool(facts_obj.related_order_ids), src),
        ]
        missing, nxt = self._annotate(
            case.case_id, facts, question,
            "Order lich su chi duoc dat trong customer_context, "
            "KHONG duoc dua vao affected_entities.",
        )
        handoff = Handoff(
            case_id=case.case_id, question=question, from_agent=self.name,
            to_agent="coordinator", facts=facts,
            missing_or_conflicting=missing, suggested_next=nxt,
        )
        self.tracer.handoff(handoff)
        return facts_obj, handoff


class OrderProductAgent(BaseAgent):
    """Scope: orders, order_items, products, sellers, category_translation."""

    name = "order_product"

    def __init__(self, llm: LLMClient, tracer: Tracer,
                 tools: OrderProductTools) -> None:
        super().__init__(llm, tracer)
        self.tools = tools

    def run(self, case: CaseInput, question: str) -> tuple[Any, Handoff]:
        # Luon tinh du product/category: 'multiple_categories' la dieu kien du
        # lieu. Scope chi chan o khau xuat (Assembler).
        f = self.tools.inspect(case.claimed_order_id, include_product=True)
        src = f"order:{case.claimed_order_id}"
        facts = [
            Fact("order_status", f.order_status, src),
            Fact("item_count", f.item_count, src),
            Fact("item_ids", f.item_ids,
                 f"item:{f.item_ids[0]}" if f.item_ids else src),
            Fact("seller_ids", f.seller_ids,
                 f"seller:{f.seller_ids[0]}" if f.seller_ids else src),
            Fact("product_ids", f.product_ids, src),
            Fact("category_names", f.category_names, src),
        ]
        missing, nxt = self._annotate(
            case.case_id, facts, question,
            "Order khong co item row la truong hop hop le trong du lieu Olist.",
        )
        if f.item_count == 0:
            missing = list(dict.fromkeys(missing + ["order khong co item row"]))
        handoff = Handoff(
            case_id=case.case_id, question=question, from_agent=self.name,
            to_agent="coordinator", facts=facts,
            missing_or_conflicting=missing, suggested_next=nxt,
        )
        self.tracer.handoff(handoff)
        return f, handoff


class PaymentAgent(BaseAgent):
    """Scope: order_payments, order_items(price, freight_value)."""

    name = "payment"

    def __init__(self, llm: LLMClient, tracer: Tracer, tools: PaymentTools) -> None:
        super().__init__(llm, tracer)
        self.tools = tools

    def run(self, case: CaseInput, question: str) -> tuple[Any, Handoff]:
        f = self.tools.reconcile(case.claimed_order_id)
        src = f"order:{case.claimed_order_id}"
        pay_src = f"payment:{f.payment_ids[0]}" if f.payment_ids else src
        facts = [
            Fact("payment_rows", f.payment_rows, pay_src),
            Fact("payment_total_brl", money(f.payment_total), pay_src),
            Fact("item_total_brl", money(f.item_total), src),
            Fact("freight_total_brl", money(f.freight_total), src),
            Fact("expected_total_brl", money(f.expected_total), src),
            Fact("difference_brl", money(f.difference), src),
            Fact("reconciled", f.reconciled, src),
            Fact("payment_types", f.payment_types, pay_src),
        ]
        missing, nxt = self._annotate(
            case.case_id, facts, question,
            "Order khong co item row -> expected/difference/reconciled phai la null.",
        )
        if f.reconciled is False:
            missing = list(dict.fromkeys(
                missing + [f"payment lech {money(f.difference)} BRL so voi expected"]
            ))
        handoff = Handoff(
            case_id=case.case_id, question=question, from_agent=self.name,
            to_agent="coordinator", facts=facts,
            missing_or_conflicting=missing, suggested_next=nxt,
        )
        self.tracer.handoff(handoff)
        return f, handoff


class DeliveryAgent(BaseAgent):
    """Scope: orders(timestamps), order_items(shipping_limit_date, seller_id)."""

    name = "delivery"

    def __init__(self, llm: LLMClient, tracer: Tracer, tools: DeliveryTools) -> None:
        super().__init__(llm, tracer)
        self.tools = tools

    def run(self, case: CaseInput, question: str) -> tuple[Any, Handoff]:
        f = self.tools.analyse(case.claimed_order_id)
        src = f"order:{case.claimed_order_id}"
        facts = [
            Fact("delivered_at", f.delivered_at, src),
            Fact("estimated_delivery_at", f.estimated_delivery_at, src),
            Fact("carrier_handoff_at", f.carrier_handoff_at, src),
            Fact("delivery_variance_hours", f.delivery_variance_hours, src),
            Fact("seller_handoff_analysis", f.seller_handoff_analysis,
                 f"seller:{f.seller_handoff_analysis[0]['seller_id']}"
                 if f.seller_handoff_analysis else src),
            Fact("late_handoff_seller_ids", f.late_handoff_seller_ids, src),
        ]
        missing, nxt = self._annotate(
            case.case_id, facts, question,
            "carrier_handoff_at null -> khong the ket luan seller ban giao tre.",
        )
        if f.delivered_at is None:
            missing = list(dict.fromkeys(missing + ["order chua tung duoc giao"]))
        if f.carrier_handoff_at is None:
            missing = list(dict.fromkeys(missing + ["thieu order_delivered_carrier_date"]))
        handoff = Handoff(
            case_id=case.case_id, question=question, from_agent=self.name,
            to_agent="coordinator", facts=facts,
            missing_or_conflicting=missing, suggested_next=nxt,
        )
        self.tracer.handoff(handoff)
        return f, handoff


class PolicyAgent(BaseAgent):
    """Ap EC_POLICY_V2. KHONG doc CSV — chi thay EvidenceBundle.

    Chay hai nhanh song song tren cung evidence:
      - LLM tu de xuat primary_issue (khong thay ket qua rule engine)
      - PolicyEngine tinh ket qua tat dinh
    Rule engine LUON THANG. Bat dong duoc ghi trace va tru confidence.
    """

    name = "policy"

    def __init__(self, llm: LLMClient, tracer: Tracer, engine: PolicyEngine) -> None:
        super().__init__(llm, tracer)
        self.engine = engine

    def decide(self, case: CaseInput, bundle: EvidenceBundle,
               handoffs: list[Handoff]) -> tuple[PolicyDecision, bool]:
        decision = self.engine.decide(bundle)
        proposal = self._llm_proposal(case, bundle)
        agrees = proposal is None or proposal == decision.primary_issue

        if proposal is not None and proposal != decision.primary_issue:
            self.tracer.bump("policy_discrepancies")
            self.tracer.emit(
                case.case_id, "policy_discrepancy",
                llm_proposal=proposal, engine_result=decision.primary_issue,
                note="rule engine thang; LLM chi de doi chieu",
            )

        self.tracer.emit(
            case.case_id, "policy_decision",
            engine_result=decision.primary_issue,
            llm_proposal=proposal,
            agreement=agrees,
            secondary_issues=decision.secondary_issues,
            root_cause=decision.root_cause_code,
            refund_brl=money(decision.recommended_refund),
            actions=decision.resolution_actions,
            evidence_handoffs=[h.from_agent for h in handoffs],
        )
        handoff = Handoff(
            case_id=case.case_id,
            question="Ap EC_POLICY_V2 va dung ket luan cho case nay.",
            from_agent=self.name, to_agent="verifier",
            facts=[
                Fact("primary_issue", decision.primary_issue,
                     f"policy:{decision.root_cause_code}"),
                Fact("recommended_refund_brl", money(decision.recommended_refund),
                     f"policy:{decision.root_cause_code}"),
            ],
            missing_or_conflicting=(
                [] if agrees else [f"LLM de xuat '{proposal}', engine cho "
                                   f"'{decision.primary_issue}'"]
            ),
            suggested_next="Chay 10 gate truoc khi ghi file.",
        )
        self.tracer.handoff(handoff)
        return decision, agrees

    def _llm_proposal(self, case: CaseInput, b: EvidenceBundle) -> str | None:
        result = self.llm.chat_json(
            case.case_id, "policy",
            system=(
                "Ban la Policy Agent ap dung EC_POLICY_V2 cho khieu nai e-commerce. "
                "Input da chua san cac dieu kien duoi dang boolean — chi can ap "
                "thang, KHONG tu suy dien lai tu timestamp.\n"
                "Chon DUNG MOT primary_issue, xet theo thu tu, KHOP DAU TIEN THI DUNG:\n"
                "1. canceled_order_paid     <- order_status=='canceled' AND has_payment\n"
                "2. unavailable_order_paid  <- order_status=='unavailable' AND has_payment\n"
                "3. late_delivery_seller    <- delivered_later_than_estimated AND "
                "at_least_one_seller_handed_off_late\n"
                "4. late_delivery_logistics <- delivered_later_than_estimated AND NOT "
                "at_least_one_seller_handed_off_late\n"
                "5. valid_split_payment     <- payment_row_count>=2 AND "
                "payment_reconciled_within_0_10_brl==true\n"
                "6. unsupported_late_claim  <- khong dieu kien nao o tren dung\n"
                'Tra ve JSON: {"primary_issue": string, "reason": string}'
            ),
            user=json.dumps(
                {
                    # Dieu kien DA SUY DIEN SAN. Truoc day chi gui so lieu tho
                    # va bat LLM tu suy ra 'giao tre'/'seller tre' -> no roi ve
                    # nhanh mac dinh unsupported_late_claim trong 5/12 case.
                    "order_status": b.order_product.order_status,
                    "has_payment": b.paid,
                    "delivered_later_than_estimated": b.delivered_late,
                    "at_least_one_seller_handed_off_late": b.seller_late,
                    "payment_row_count": b.payment.payment_rows,
                    "payment_reconciled_within_0_10_brl": b.payment.reconciled,
                    # So lieu tho de doi chieu
                    "payment_total_brl": money(b.payment.payment_total),
                    "difference_brl": money(b.payment.difference),
                    "delivered_at": b.delivery.delivered_at,
                    "estimated_delivery_at": b.delivery.estimated_delivery_at,
                    "delivery_variance_hours": b.delivery.delivery_variance_hours,
                    "late_handoff_seller_ids": b.delivery.late_handoff_seller_ids,
                    "item_count": b.order_product.item_count,
                },
                ensure_ascii=False,
            ),
        )
        if not result:
            return None
        proposal = result.get("primary_issue")
        return proposal if proposal in ROOT_CAUSE_OF else None


class VerifierAgent(BaseAgent):
    """10 gate tat dinh + soat nhat quan ngu nghia bang LLM khac ho model."""

    name = "verifier"

    def __init__(self, llm: LLMClient, tracer: Tracer, verifier: Verifier) -> None:
        super().__init__(llm, tracer)
        self.verifier = verifier

    def check(self, case: CaseInput, out: dict[str, Any]) -> list[GateFailure]:
        failures = self.verifier.run(out)
        for f in failures:
            self.tracer.bump("gate_failures")
            self.tracer.emit(case.case_id, "gate_fail", code=f.code,
                             message=f.message, stage=f.stage)
        if not failures:
            self._semantic_review(case, out)
        return failures

    def _semantic_review(self, case: CaseInput, out: dict[str, Any]) -> None:
        result = self.llm.chat_json(
            case.case_id, "verifier",
            system=(
                "Ban la Verifier doc lap. Toan bo kiem tra schema, ID va so hoc DA "
                "duoc chay va deu PASS. Nhiem vu cua ban chi la soat tinh nhat quan "
                "NGU NGHIA: ket luan co hop ly voi bang chung khong? Ban KHONG duoc "
                "de xuat sua so lieu. "
                'Tra ve JSON: {"consistent": boolean, "warnings": [string]}'
            ),
            user=json.dumps(out, ensure_ascii=False, default=str),
        )
        if result and result.get("warnings"):
            self.tracer.emit(
                case.case_id, "verifier_semantic_warning",
                consistent=bool(result.get("consistent", True)),
                warnings=[str(w) for w in result["warnings"]][:5],
            )


# ---------------------------------------------------------------------------
# CaseRunner — orchestration
# ---------------------------------------------------------------------------

MAX_RETRIES = 2


class CaseRunner:
    def __init__(self, store: DataStore, tracer: Tracer, llm: LLMClient,
                 variant: Any = None) -> None:
        self.store = store
        self.tracer = tracer
        self.llm = llm

        self.coordinator = CoordinatorAgent(llm, tracer)
        self.specialists: dict[str, Any] = {
            "customer": CustomerAgent(llm, tracer, CustomerTools(store)),
            "order_product": OrderProductAgent(llm, tracer, OrderProductTools(store)),
            "payment": PaymentAgent(llm, tracer, PaymentTools(store)),
            "delivery": DeliveryAgent(llm, tracer, DeliveryTools(store)),
        }
        self.policy = PolicyAgent(llm, tracer, PolicyEngine(variant))
        self.verifier = VerifierAgent(llm, tracer, Verifier(store))
        self.assembler = Assembler(variant)

    def run(self, case: CaseInput) -> dict[str, Any]:
        self.tracer.emit(case.case_id, "case_start",
                         order_id=case.claimed_order_id,
                         policy_version=case.policy_version)

        if case.policy_version != "EC_POLICY_V2":
            self.tracer.emit(case.case_id, "warning",
                             code="POLICY_VERSION_MISMATCH",
                             got=case.policy_version, applied="EC_POLICY_V2")

        if not self.store.order_exists(case.claimed_order_id):
            # De bai doi du 50 file; thieu file la hard gate. Tha mat diem mot
            # case con hon hong ca lot chay.
            self.tracer.emit(case.case_id, "warning", code="UNKNOWN_ORDER",
                             order_id=case.claimed_order_id)
            out = self._empty_output(case)
            self.tracer.emit(case.case_id, "case_end", status="unknown_order")
            return out

        failed: list[GateFailure] = []
        out: dict[str, Any] = {}

        for attempt in range(MAX_RETRIES + 1):
            if attempt:
                self.tracer.bump("retries")
                self.tracer.emit(case.case_id, "retry", attempt=attempt,
                                 gates=[g.code for g in failed])

            plan = self.coordinator.plan(case, failed)
            bundle, handoffs = self._gather(case, plan)
            decision, agrees = self.policy.decide(case, bundle, handoffs)

            out, truncated = self.assembler.build(
                bundle, decision, compute_confidence(bundle, agrees, False)
            )
            if truncated:
                out["case_assessment"]["confidence"] = compute_confidence(
                    bundle, agrees, True
                )

            failed = self.verifier.check(case, out)
            if not failed:
                self.tracer.emit(case.case_id, "case_end", status="pass",
                                 attempt=attempt,
                                 primary_issue=decision.primary_issue)
                return out

        self.tracer.emit(case.case_id, "case_end", status="verifier_exhausted",
                         gates=[g.code for g in failed])
        return out

    # -- noi bo -------------------------------------------------------------

    def _gather(self, case: CaseInput,
                plan: dict[str, Any]) -> tuple[EvidenceBundle, list[Handoff]]:
        """Fan-out toi cac specialist roi gop thanh EvidenceBundle.

        Coordinator chi thay ket qua qua Handoff — no khong co tool du lieu nao.
        """
        results: dict[str, Any] = {}
        handoffs: list[Handoff] = []
        questions = plan["questions"]

        for name in plan["agents"]:
            agent = self.specialists.get(name)
            if agent is None:
                continue
            facts, handoff = agent.run(case, questions.get(name, ""))
            results[name] = facts
            handoffs.append(handoff)

        from core import CustomerFacts, OrderProductFacts, PaymentFacts, DeliveryFacts

        bundle = EvidenceBundle(
            case_id=case.case_id,
            order_id=case.claimed_order_id,
            order_exists=True,
            customer=results.get("customer") or CustomerFacts(),
            order_product=results.get("order_product") or OrderProductFacts(),
            payment=results.get("payment") or PaymentFacts(),
            delivery=results.get("delivery") or DeliveryFacts(),
            include_customer_history=case.include_customer_history,
            include_product_context=case.include_product_context,
        )
        self.tracer.emit(
            case.case_id, "evidence_bundle",
            contributing_agents=[h.from_agent for h in handoffs],
            fact_count=sum(len(h.facts) for h in handoffs),
            unresolved=[m for h in handoffs for m in h.missing_or_conflicting],
        )
        return bundle, handoffs

    @staticmethod
    def _empty_output(case: CaseInput) -> dict[str, Any]:
        """Output hop le toi thieu khi claimed_order_id khong ton tai."""
        return {
            "case_id": case.case_id,
            "case_assessment": {
                "primary_issue": "unsupported_late_claim",
                "secondary_issues": [],
                "case_status": "no_action",
                "confidence": 0.5,
            },
            "affected_entities": {
                "order_ids": [], "item_ids": [], "seller_ids": [], "payment_ids": [],
            },
            "customer_context": {"customer_unique_id": None, "related_order_ids": []},
            "product_context": {"product_ids": [], "category_names": []},
            "delivery_analysis": {
                "delivered_at": None, "estimated_delivery_at": None,
                "carrier_handoff_at": None, "delivery_variance_hours": None,
                "seller_handoff_analysis": [], "late_handoff_seller_ids": [],
            },
            "payment_reconciliation": {
                "currency": "BRL", "item_total_brl": 0.0, "freight_total_brl": 0.0,
                "expected_total_brl": None, "payment_total_brl": 0.0,
                "difference_brl": None, "reconciled": None, "payment_types": [],
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": "DELIVERY_WITHIN_ESTIMATE", "rank": 1}],
                "responsible_parties": [],
            },
            "evidence_ids": ["policy:DELIVERY_WITHIN_ESTIMATE"],
            "financial_resolution": {"currency": "BRL", "recommended_refund_brl": 0.0},
            "resolution_actions": ["reject_late_refund"],
        }
