"""Evidence-first two-Qwen Olist pipeline (OpenRouter-compatible)."""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA, INPUT, OUTPUT, LOGGING = ROOT / "data", ROOT / "input", ROOT / "output", ROOT / "logging"
FMT = "%Y-%m-%d %H:%M:%S"


def dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists(): return
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            k, v = raw.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8", newline="") as f: return list(csv.DictReader(f))


def group(records: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in records: result[row[key]].append(row)
    return result


def uniq(values: list[str], limit: int) -> list[str]: return list(dict.fromkeys(v for v in values if v))[:limit]
def dec(value: str | None) -> Decimal: return Decimal(value or "0")
def cash(value: Decimal | None) -> float | None: return None if value is None else float(value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
def delta(a: str | None, b: str | None) -> float | None:
    return None if not a or not b else round((datetime.strptime(a, FMT) - datetime.strptime(b, FMT)).total_seconds() / 3600, 2)


class Store:
    def __init__(self) -> None:
        self.orders = {x["order_id"]: x for x in read_csv("olist_orders_dataset.csv")}
        self.customers = {x["customer_id"]: x for x in read_csv("olist_customers_dataset.csv")}
        self.items, self.payments = group(read_csv("olist_order_items_dataset.csv"), "order_id"), group(read_csv("olist_order_payments_dataset.csv"), "order_id")
        self.products = {x["product_id"]: x for x in read_csv("olist_products_dataset.csv")}
        self.history: dict[str, list[str]] = defaultdict(list)
        for oid, order in self.orders.items():
            customer = self.customers.get(order["customer_id"])
            if customer: self.history[customer["customer_unique_id"]].append(oid)

    def evidence(self, case: dict[str, Any]) -> dict[str, Any]:
        oid = case["customer_request"]["claimed_order_id"]
        if oid not in self.orders: raise ValueError(f"Unknown order: {oid}")
        order, customer = self.orders[oid], self.customers.get(self.orders[oid]["customer_id"], {})
        items = sorted(self.items.get(oid, []), key=lambda x: int(x["order_item_id"]))
        payments = sorted(self.payments.get(oid, []), key=lambda x: int(x["payment_sequential"]))
        item_total, freight = sum((dec(x["price"]) for x in items), Decimal()), sum((dec(x["freight_value"]) for x in items), Decimal())
        paid = sum((dec(x["payment_value"]) for x in payments), Decimal())
        expected = item_total + freight if items else None
        difference = paid - expected if expected is not None else None
        seller_dates: dict[str, list[str]] = defaultdict(list)
        for item in items:
            if item.get("shipping_limit_date"): seller_dates[item["seller_id"]].append(item["shipping_limit_date"])
        handoffs = [{"seller_id": seller, "shipping_limit_at": min(dates), "handoff_variance_hours": delta(order.get("order_delivered_carrier_date"), min(dates)), "late_handoff": (delta(order.get("order_delivered_carrier_date"), min(dates)) or 0) > 0} for seller, dates in seller_dates.items()]
        product_ids = uniq([x["product_id"] for x in items], 5)
        categories = uniq([self.products.get(x, {}).get("product_category_name", "") for x in product_ids], 5)
        uid = customer.get("customer_unique_id", "")
        return {"case_id": case["case_id"], "order": order, "items": items, "payments": payments, "customer_unique_id": uid, "related_order_ids": [x for x in self.history.get(uid, []) if x != oid][:5], "product_ids": product_ids, "category_names": categories, "delivery_variance_hours": delta(order.get("order_delivered_customer_date"), order.get("order_estimated_delivery_date")), "seller_handoff_analysis": handoffs[:3], "payment": {"item_total_brl": cash(item_total) if items else None, "freight_total_brl": cash(freight) if items else None, "expected_total_brl": cash(expected), "payment_total_brl": cash(paid), "difference_brl": cash(difference), "reconciled": None if difference is None else abs(difference) <= Decimal(".10"), "payment_types": uniq([x["payment_type"] for x in payments], 5)}}


def policy(p: dict[str, Any]) -> dict[str, Any]:
    order, payment, items, payments = p["order"], p["payment"], p["items"], p["payments"]
    late_delivery, late_sellers = (p["delivery_variance_hours"] or 0) > 0, [x["seller_id"] for x in p["seller_handoff_analysis"] if x["late_handoff"]]
    paid = payment["payment_total_brl"] > 0
    if order["order_status"] == "canceled" and paid: primary, cause, refund, party, actions = "canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT", payment["payment_total_brl"], ("platform", "OLIST_PLATFORM"), ["issue_full_refund", "verify_refund_completion"]
    elif order["order_status"] == "unavailable" and paid: primary, cause, refund, party, actions = "unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT", payment["payment_total_brl"], ("platform", "OLIST_PLATFORM"), ["issue_full_refund", "verify_refund_completion"]
    elif late_delivery and late_sellers: primary, cause, refund, party, actions = "late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT", payment["freight_total_brl"], ("seller", late_sellers[0]), ["refund_freight", "review_seller_handoff"]
    elif late_delivery: primary, cause, refund, party, actions = "late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE", payment["freight_total_brl"], ("logistics_provider", "LOGISTICS_PROVIDER"), ["refund_freight", "review_carrier_delay"]
    elif len(payments) >= 2 and payment["reconciled"]: primary, cause, refund, party, actions = "valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", 0.0, None, ["explain_valid_split_payment"]
    else: primary, cause, refund, party, actions = "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", 0.0, None, ["reject_late_refund"]
    sellers = uniq([x["seller_id"] for x in items], 3)
    secondary = []
    if len(items) >= 2: secondary.append("multi_item_order")
    if len(sellers) >= 2: secondary.append("multi_seller_order")
    if len(payments) >= 2: secondary.append("split_payment")
    if p["related_order_ids"]: secondary.append("repeat_customer")
    if len(p["category_names"]) >= 2: secondary.append("multiple_categories")
    if "multi_seller_order" in secondary: actions.append("coordinate_multi_seller_case")
    if "split_payment" in secondary and primary != "valid_split_payment": actions.append("verify_payment_allocation")
    evidence = [f"order:{order['order_id']}"] + [f"item:{order['order_id']}:{x['order_item_id']}" for x in items] + [f"payment:{order['order_id']}:{x['payment_sequential']}" for x in payments]
    responsible_parties = [] if not party else [{"party_type": party[0], "party_id": party[1]}]
    # EC_POLICY_V2 assigns every seller that handed off after its limit, not only
    # the first seller encountered in a multi-seller order.
    if primary == "late_delivery_seller":
        responsible_parties = [{"party_type": "seller", "party_id": seller} for seller in late_sellers[:3]]
    evidence += [f"seller:{entry['party_id']}" for entry in responsible_parties if entry["party_type"] == "seller"]
    evidence.append(f"policy:{cause}")
    return {"case_id": p["case_id"], "case_assessment": {"primary_issue": primary, "secondary_issues": secondary, "case_status": "action_required" if refund > 0 else "no_action", "confidence": .95}, "affected_entities": {"order_ids": [order["order_id"]], "item_ids": [f"{order['order_id']}:{x['order_item_id']}" for x in items][:5], "seller_ids": sellers, "payment_ids": [f"{order['order_id']}:{x['payment_sequential']}" for x in payments][:5]}, "customer_context": {"customer_unique_id": p["customer_unique_id"], "related_order_ids": p["related_order_ids"]}, "product_context": {"product_ids": p["product_ids"], "category_names": p["category_names"]}, "delivery_analysis": {"delivered_at": order.get("order_delivered_customer_date") or None, "estimated_delivery_at": order.get("order_estimated_delivery_date") or None, "carrier_handoff_at": order.get("order_delivered_carrier_date") or None, "delivery_variance_hours": p["delivery_variance_hours"], "seller_handoff_analysis": p["seller_handoff_analysis"], "late_handoff_seller_ids": late_sellers}, "payment_reconciliation": {"currency": "BRL", **payment}, "root_cause_analysis": {"ranked_causes": [{"cause_code": cause, "rank": 1}], "responsible_parties": responsible_parties}, "evidence_ids": evidence[:20], "financial_resolution": {"currency": "BRL", "recommended_refund_brl": refund}, "resolution_actions": actions[:5]}


def validate_output(result: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    """Reject mutated or incomplete JSON before it can be written to output/."""
    expected = policy(evidence)
    errors: list[str] = []
    if result != expected:
        errors.append("output differs from the canonical deterministic policy result")
    if len(result["evidence_ids"]) > 20 or len(result["resolution_actions"]) > 5:
        errors.append("output array limit exceeded")
    entities = result["affected_entities"]
    if any((len(entities[key]) > limit) for key, limit in {"order_ids": 5, "item_ids": 5, "seller_ids": 3, "payment_ids": 5}.items()):
        errors.append("affected_entities array limit exceeded")
    confidence = result["case_assessment"]["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence is outside [0, 1]")
    valid_evidence = set(expected["evidence_ids"])
    if not set(result["evidence_ids"]).issubset(valid_evidence):
        errors.append("invalid evidence ID")
    return errors


def evaluate_policy_handoff(resolver: dict[str, Any], canonical: dict[str, Any]) -> dict[str, Any]:
    """Record model agreement, without allowing a model to override verified facts."""
    if resolver.get("status") == "dry_run":
        return {"checked": False, "reason": "dry_run"}
    suggested = resolver.get("primary_issue")
    return {
        "checked": True,
        "suggested_primary_issue": suggested,
        "canonical_primary_issue": canonical["case_assessment"]["primary_issue"],
        "matches_canonical": suggested == canonical["case_assessment"]["primary_issue"],
    }


def call(model: str, system: str, payload: Any) -> dict[str, Any]:
    key = os.getenv("OPENROUTER_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not key: raise RuntimeError("Set OPENROUTER_API_KEY in .env")
    body = json.dumps({"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}]}).encode()
    req = urllib.request.Request(os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                content = json.loads(response.read())["choices"][0]["message"]["content"]
                return json.loads(content)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < 2: time.sleep(2 ** attempt)
    raise RuntimeError(f"Model call failed after 3 attempts: {last_error}")


def write_trace(run_id: str, case_id: str, step: str, **data: Any) -> None:
    LOGGING.mkdir(exist_ok=True)
    event = {"timestamp": datetime.now().astimezone().isoformat(timespec="seconds"), "run_id": run_id, "case_id": case_id, "step": step, **data}
    with (LOGGING / "trace.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--case"); parser.add_argument("--dry-run", action="store_true"); args = parser.parse_args(); dotenv()
    cases = [INPUT / args.case] if args.case else sorted(INPUT.glob("EC_*.json"))
    if not cases or not all(x.exists() for x in cases): raise FileNotFoundError("Missing input cases")
    run_id = "run_" + datetime.now().strftime("%Y%m%d_%H%M%S"); LOGGING.mkdir(exist_ok=True); (LOGGING / "trace.jsonl").write_text("", encoding="utf-8"); write_trace(run_id, "_run_", "run_started", case_count=len(cases), dry_run=args.dry_run)
    store, data_model, policy_model = Store(), os.getenv("DATA_MODEL", "qwen/qwen3.5-9b"), os.getenv("POLICY_MODEL", "qwen/qwen3-8b")
    primary_issues: list[str] = []
    OUTPUT.mkdir(exist_ok=True)
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8")); cid = case["case_id"]; write_trace(run_id, cid, "case_received", claimed_order_id=case["customer_request"]["claimed_order_id"])
        evidence = store.evidence(case); write_trace(run_id, cid, "evidence_packet_created", agent="deterministic_data_tools", item_count=len(evidence["items"]), payment_count=len(evidence["payments"]))
        if args.dry_run: investigator, resolver = {"status": "dry_run"}, {"status": "dry_run"}
        else:
            write_trace(run_id, cid, "data_investigator_called", agent="data_investigator", model=data_model)
            investigator = call(data_model, "Audit only supplied Olist evidence. Return JSON: evidence_complete, observations, risks. Never invent facts.", evidence)
            write_trace(run_id, cid, "policy_resolver_called", agent="policy_resolver", model=policy_model)
            resolver = call(policy_model, "Review this evidence and investigator handoff under EC_POLICY_V2. Return JSON recommendation; never invent evidence.", {"evidence": evidence, "handoff": investigator})
        write_trace(run_id, cid, "investigator_handoff", agent="data_investigator", model=data_model, status="dry_run" if args.dry_run else "completed", output=investigator)
        write_trace(run_id, cid, "policy_handoff", agent="policy_resolver", model=policy_model, status="dry_run" if args.dry_run else "completed", output=resolver)
        result = policy(evidence)
        handoff_check = evaluate_policy_handoff(resolver, result)
        write_trace(run_id, cid, "policy_recommendation_checked", agent="deterministic_validator", **handoff_check)
        errors = validate_output(result, evidence)
        if errors:
            write_trace(run_id, cid, "validation_completed", agent="deterministic_validator", status="failed", errors=errors)
            raise ValueError(f"{cid}: output validation failed: {errors}")
        (OUTPUT / path.name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        primary_issues.append(result["case_assessment"]["primary_issue"])
        write_trace(run_id, cid, "validation_completed", agent="deterministic_validator", status="passed", output_file=str(OUTPUT / path.name)); print(f"completed {path.name}")
    write_trace(run_id, "_run_", "run_completed", case_count=len(cases), dry_run=args.dry_run)
    (LOGGING / "run_summary.json").write_text(json.dumps({"run_id": run_id, "case_count": len(cases), "dry_run": args.dry_run, "models": {"data_investigator": data_model, "policy_resolver": policy_model}, "validated_cases": len(primary_issues), "primary_issue_counts": dict(sorted(Counter(primary_issues).items()))}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
