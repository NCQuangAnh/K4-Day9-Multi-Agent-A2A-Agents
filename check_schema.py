"""
check_schema.py — Kiem tra schema output/ theo README §6, BAO CAO TUNG FILE.

Khac voi 10 gate trong core.Verifier (kiem tra tinh nhat quan NGHIEP VU),
file nay so khop CAU TRUC: dung ten key, dung kieu, khong thieu, khong thua.

    python check_schema.py                 # kiem tra output/
    python check_schema.py variants/combo  # kiem tra mot thu muc khac
    python check_schema.py output --quiet  # chi in file loi
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
NUM = (int, float)

# --- Cau truc bat buoc, dung theo vi du README §6 ---------------------------

TOP_KEYS = [
    "case_id", "case_assessment", "affected_entities", "customer_context",
    "product_context", "delivery_analysis", "payment_reconciliation",
    "root_cause_analysis", "evidence_ids", "financial_resolution",
    "resolution_actions",
]
NESTED_KEYS = {
    "case_assessment": ["primary_issue", "secondary_issues", "case_status", "confidence"],
    "affected_entities": ["order_ids", "item_ids", "seller_ids", "payment_ids"],
    "customer_context": ["customer_unique_id", "related_order_ids"],
    "product_context": ["product_ids", "category_names"],
    "delivery_analysis": ["delivered_at", "estimated_delivery_at", "carrier_handoff_at",
                          "delivery_variance_hours", "seller_handoff_analysis",
                          "late_handoff_seller_ids"],
    "payment_reconciliation": ["currency", "item_total_brl", "freight_total_brl",
                               "expected_total_brl", "payment_total_brl",
                               "difference_brl", "reconciled", "payment_types"],
    "root_cause_analysis": ["ranked_causes", "responsible_parties"],
    "financial_resolution": ["currency", "recommended_refund_brl"],
}
# (duong dan, kieu, cho phep null)
SPEC: list[tuple[str, Any, bool]] = [
    ("case_id", str, False),
    ("case_assessment.primary_issue", str, False),
    ("case_assessment.secondary_issues", list, False),
    ("case_assessment.case_status", str, False),
    ("case_assessment.confidence", NUM, False),
    ("affected_entities.order_ids", list, False),
    ("affected_entities.item_ids", list, False),
    ("affected_entities.seller_ids", list, False),
    ("affected_entities.payment_ids", list, False),
    ("customer_context.customer_unique_id", str, True),
    ("customer_context.related_order_ids", list, False),
    ("product_context.product_ids", list, False),
    ("product_context.category_names", list, False),
    ("delivery_analysis.delivered_at", str, True),
    ("delivery_analysis.estimated_delivery_at", str, True),
    ("delivery_analysis.carrier_handoff_at", str, True),
    ("delivery_analysis.delivery_variance_hours", NUM, True),
    ("delivery_analysis.seller_handoff_analysis", list, False),
    ("delivery_analysis.late_handoff_seller_ids", list, False),
    ("payment_reconciliation.currency", str, False),
    ("payment_reconciliation.item_total_brl", NUM, True),
    ("payment_reconciliation.freight_total_brl", NUM, True),
    ("payment_reconciliation.expected_total_brl", NUM, True),
    ("payment_reconciliation.payment_total_brl", NUM, True),
    ("payment_reconciliation.difference_brl", NUM, True),
    ("payment_reconciliation.reconciled", bool, True),
    ("payment_reconciliation.payment_types", list, False),
    ("root_cause_analysis.ranked_causes", list, False),
    ("root_cause_analysis.responsible_parties", list, False),
    ("evidence_ids", list, False),
    ("financial_resolution.currency", str, False),
    ("financial_resolution.recommended_refund_brl", NUM, False),
    ("resolution_actions", list, False),
]
LIMITS = {
    "affected_entities.order_ids": 5, "affected_entities.item_ids": 5,
    "affected_entities.seller_ids": 3, "affected_entities.payment_ids": 5,
    "customer_context.related_order_ids": 5, "product_context.product_ids": 5,
    "product_context.category_names": 5, "root_cause_analysis.ranked_causes": 3,
    "root_cause_analysis.responsible_parties": 3, "evidence_ids": 20,
    "resolution_actions": 5,
}
PRIMARY = {"canceled_order_paid", "unavailable_order_paid", "late_delivery_seller",
           "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim"}
SECONDARY = ["multi_item_order", "multi_seller_order", "split_payment",
             "repeat_customer", "multiple_categories"]
CAUSES = {"SELLER_HANDOFF_AFTER_LIMIT", "CARRIER_DELIVERED_AFTER_ESTIMATE",
          "ORDER_CANCELED_AFTER_PAYMENT", "ORDER_UNAVAILABLE_AFTER_PAYMENT",
          "MULTIPLE_PAYMENTS_RECONCILED", "DELIVERY_WITHIN_ESTIMATE"}
ACTIONS = {"issue_full_refund", "refund_freight", "explain_valid_split_payment",
           "reject_late_refund", "review_seller_handoff", "review_carrier_delay",
           "verify_refund_completion", "coordinate_multi_seller_case",
           "verify_payment_allocation"}
HANDOFF_KEYS = {"seller_id", "shipping_limit_at", "handoff_variance_hours", "late_handoff"}
CAUSE_KEYS = {"cause_code", "rank"}
PARTY_KEYS = {"party_type", "party_id"}
TS = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
EVIDENCE = [re.compile(p) for p in (
    r"^order:[0-9a-f]{32}$", r"^item:[0-9a-f]{32}:\d+$",
    r"^payment:[0-9a-f]{32}:\d+$", r"^seller:[0-9a-f]{32}$", r"^policy:[A-Z_]+$")]

MISSING = object()

# Ten 9 nhom kiem tra, in theo tung file
CHECKS = ["encode", "keys", "types", "limits", "enum", "order", "nested",
          "timestamp", "round"]


def dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return MISSING
        cur = cur[part]
    return cur


def check_file(path: Path) -> tuple[dict[str, list[str]], dict[str, Any] | None]:
    """Tra ve ({nhom_kiem_tra: [loi]}, du_lieu)."""
    err: dict[str, list[str]] = {c: [] for c in CHECKS}

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        err["encode"].append("file co BOM UTF-8 (pipeline khong bao gio ghi BOM)")
    if b'"N/A"' in raw:
        err["encode"].append('chua chuoi "N/A" — file bi cong cu ngoai ghi de')
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        err["encode"].append(f"khong parse duoc JSON: {exc}")
        return err, None

    # 1. key cap 1 + key long nhau: khong thieu, khong thua
    got = set(d)
    for k in sorted(got - set(TOP_KEYS)):
        err["keys"].append(f"THUA key cap 1 '{k}'")
    for k in sorted(set(TOP_KEYS) - got):
        err["keys"].append(f"THIEU key cap 1 '{k}'")
    for parent, keys in NESTED_KEYS.items():
        if not isinstance(d.get(parent), dict):
            continue
        sub = set(d[parent])
        for k in sorted(sub - set(keys)):
            err["keys"].append(f"THUA '{parent}.{k}'")
        for k in sorted(set(keys) - sub):
            err["keys"].append(f"THIEU '{parent}.{k}'")

    # 2. kieu du lieu + null
    for p, typ, nullable in SPEC:
        v = dig(d, p)
        if v is MISSING:
            err["types"].append(f"thieu '{p}'")
        elif v is None:
            if not nullable:
                err["types"].append(f"'{p}' = null (khong duoc phep)")
        elif isinstance(v, bool) and typ is NUM:
            err["types"].append(f"'{p}' la bool, can so")
        elif not isinstance(v, typ):
            err["types"].append(f"'{p}' la {type(v).__name__}")

    # 3. gioi han mang
    for p, lim in LIMITS.items():
        v = dig(d, p)
        if isinstance(v, list) and len(v) > lim:
            err["limits"].append(f"'{p}' co {len(v)} > {lim}")

    # 4. gia tri thuoc tap hop cho phep
    ca = d.get("case_assessment", {})
    if ca.get("primary_issue") not in PRIMARY:
        err["enum"].append(f"primary_issue = {ca.get('primary_issue')!r}")
    if ca.get("case_status") not in ("action_required", "no_action"):
        err["enum"].append(f"case_status = {ca.get('case_status')!r}")
    c = ca.get("confidence")
    if isinstance(c, NUM) and not isinstance(c, bool) and not 0 <= c <= 1:
        err["enum"].append(f"confidence = {c} ngoai [0,1]")
    for a in d.get("resolution_actions", []):
        if a not in ACTIONS:
            err["enum"].append(f"action la {a!r}")
    for e in d.get("evidence_ids", []):
        if not any(p.match(str(e)) for p in EVIDENCE):
            err["enum"].append(f"evidence sai dinh dang: {e!r}")

    # 5. thu tu bat buoc
    sec = ca.get("secondary_issues", [])
    unknown = [x for x in sec if x not in SECONDARY]
    if unknown:
        err["order"].append(f"secondary la {unknown}")
    elif sec != [x for x in SECONDARY if x in sec]:
        err["order"].append(f"secondary sai thu tu: {sec}")

    # 6. cau truc phan tu trong mang long nhau
    for s in d.get("delivery_analysis", {}).get("seller_handoff_analysis", []):
        if not isinstance(s, dict) or set(s) != HANDOFF_KEYS:
            err["nested"].append(f"seller_handoff_analysis sai key: {s}")
            continue
        if not isinstance(s["late_handoff"], bool):
            err["nested"].append("late_handoff khong phai bool")
    for rc in d.get("root_cause_analysis", {}).get("ranked_causes", []):
        if not isinstance(rc, dict) or set(rc) != CAUSE_KEYS:
            err["nested"].append(f"ranked_causes sai key: {rc}")
        elif rc["cause_code"] not in CAUSES:
            err["nested"].append(f"cause_code = {rc['cause_code']!r}")
    for rp in d.get("root_cause_analysis", {}).get("responsible_parties", []):
        if not isinstance(rp, dict) or set(rp) != PARTY_KEYS:
            err["nested"].append(f"responsible_parties sai key: {rp}")

    # 7. timestamp
    da = d.get("delivery_analysis", {})
    cands = [(k, da.get(k)) for k in
             ("delivered_at", "estimated_delivery_at", "carrier_handoff_at")]
    cands += [("shipping_limit_at", s.get("shipping_limit_at"))
              for s in da.get("seller_handoff_analysis", []) if isinstance(s, dict)]
    for k, v in cands:
        if v is not None and not TS.match(str(v)):
            err["timestamp"].append(f"{k} = {v!r}")

    # 8. lam tron 2 chu so
    for p, _t, _n in SPEC:
        v = dig(d, p)
        if isinstance(v, float) and round(v, 2) != v:
            err["round"].append(f"'{p}' = {v}")
    for s in da.get("seller_handoff_analysis", []):
        v = s.get("handoff_variance_hours") if isinstance(s, dict) else None
        if isinstance(v, float) and round(v, 2) != v:
            err["round"].append(f"handoff_variance_hours = {v}")

    # 9. rang buoc chuoi khac
    if d.get("case_id") != path.stem:
        err["keys"].append(f"case_id {d.get('case_id')!r} khong khop ten file")
    for blk in ("payment_reconciliation", "financial_resolution"):
        if d.get(blk, {}).get("currency") != "BRL":
            err["enum"].append(f"{blk}.currency != 'BRL'")

    return err, d


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    quiet = "--quiet" in sys.argv
    target = ROOT / (args[0] if args else "output")

    files = sorted(target.glob("EC_*.json"))
    if not files:
        print(f"[!] Khong tim thay file EC_*.json nao trong {target}")
        return 1

    print(f"\n=== KIEM TRA SCHEMA README §6 — {target} ===\n")
    head = f"{'file':<10} {'ket qua':<7} " + " ".join(f"{c:<9}" for c in CHECKS)
    print(head)
    print("-" * len(head))

    n_fail = 0
    details: list[str] = []
    for f in files:
        err, d = check_file(f)
        bad = {k: v for k, v in err.items() if v}
        ok = not bad
        n_fail += 0 if ok else 1
        if quiet and ok:
            continue
        cells = " ".join(f"{('OK' if not err[c] else str(len(err[c])) + ' loi'):<9}"
                         for c in CHECKS)
        print(f"{f.stem:<10} {'PASS' if ok else 'FAIL':<7} {cells}")
        if bad:
            for grp, msgs in bad.items():
                for m in msgs:
                    details.append(f"  {f.stem} [{grp}] {m}")

    print("-" * len(head))
    if details:
        print("\n--- Chi tiet loi ---")
        for line in details[:80]:
            print(line)
        if len(details) > 80:
            print(f"  ... va {len(details) - 80} loi nua")

    stray = [p.name for p in target.iterdir()
             if p.is_file() and not re.match(r"^EC_\d{3}\.json$", p.name)
             and p.name != ".gitkeep"]
    print(f"\n  So file EC_*.json : {len(files)}")
    print(f"  File PASS         : {len(files) - n_fail}")
    print(f"  File FAIL         : {n_fail}")
    print(f"  File la           : {stray or 'khong co'}")
    ok = n_fail == 0 and not stray
    print(f"\n  KET QUA: {'SCHEMA DUNG HOAN TOAN' if ok else 'CO VAN DE'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
