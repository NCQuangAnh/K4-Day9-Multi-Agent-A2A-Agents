import re
from typing import Any, Dict, List
from datetime import datetime


TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


def _is_timestamp(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, TIMESTAMP_FMT)
        return True
    except Exception:
        return False


def validate_output_schema(payload: Dict[str, Any]) -> bool:
    # Basic required keys
    required_top = [
        "case_id",
        "case_assessment",
        "affected_entities",
        "customer_context",
        "product_context",
        "delivery_analysis",
        "payment_reconciliation",
        "root_cause_analysis",
        "evidence_ids",
        "financial_resolution",
        "resolution_actions",
    ]
    if not all(key in payload for key in required_top):
        return False

    # case_assessment checks
    ca = payload["case_assessment"]
    if not isinstance(ca.get("primary_issue"), str):
        return False
    if not isinstance(ca.get("secondary_issues"), list):
        return False
    conf = ca.get("confidence")
    if not (isinstance(conf, float) or isinstance(conf, int)):
        return False
    if not (0.0 <= float(conf) <= 1.0):
        return False

    # affected_entities arrays
    ae = payload["affected_entities"]
    for k in ["order_ids", "item_ids", "seller_ids", "payment_ids"]:
        if k not in ae or not isinstance(ae[k], list):
            return False

    # customer_context
    cc = payload["customer_context"]
    if "customer_unique_id" not in cc or "related_order_ids" not in cc:
        return False

    # product_context
    pc = payload["product_context"]
    if "product_ids" not in pc or "category_names" not in pc:
        return False

    # delivery_analysis timestamps and numeric fields
    da = payload["delivery_analysis"]
    for t in ["delivered_at", "estimated_delivery_at", "carrier_handoff_at"]:
        if t not in da or not _is_timestamp(da[t]):
            return False
    if not isinstance(da.get("seller_handoff_analysis"), list):
        return False
    # seller_handoff entries
    for entry in da.get("seller_handoff_analysis", []):
        if not isinstance(entry.get("seller_id"), str):
            return False
        if not _is_timestamp(entry.get("shipping_limit_at")):
            return False
        if not (isinstance(entry.get("handoff_variance_hours"), float) or isinstance(entry.get("handoff_variance_hours"), int) or entry.get("handoff_variance_hours") is None):
            return False
        if not isinstance(entry.get("late_handoff"), bool):
            return False

    # payment_reconciliation numeric fields
    pr = payload["payment_reconciliation"]
    for num_k in ["item_total_brl", "freight_total_brl", "expected_total_brl", "payment_total_brl", "difference_brl"]:
        v = pr.get(num_k)
        if v is not None and not (isinstance(v, float) or isinstance(v, int)):
            return False
    if not isinstance(pr.get("reconciled"), bool) and pr.get("reconciled") is not None:
        return False

    # root_cause_analysis
    rca = payload["root_cause_analysis"]
    if not isinstance(rca.get("ranked_causes"), list) or not isinstance(rca.get("responsible_parties"), list):
        return False

    # evidence ids format
    evidences = payload.get("evidence_ids", [])
    ev_re = re.compile(r"^(order:[^,\s]+|item:[^,\s]+:[^,\s]+|payment:[^,\s]+:[^,\s]+|seller:[^,\s]+|policy:[A-Z0-9_]+)$")
    for e in evidences:
        if not isinstance(e, str) or not ev_re.match(e):
            return False

    # financial_resolution
    fr = payload["financial_resolution"]
    if not (isinstance(fr.get("recommended_refund_brl"), float) or isinstance(fr.get("recommended_refund_brl"), int) or fr.get("recommended_refund_brl") is None):
        return False

    # resolution_actions list
    if not isinstance(payload.get("resolution_actions"), list):
        return False

    return True


def enforce_limits(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["affected_entities"]["order_ids"] = payload["affected_entities"]["order_ids"][:5]
    payload["affected_entities"]["item_ids"] = payload["affected_entities"]["item_ids"][:5]
    payload["affected_entities"]["seller_ids"] = payload["affected_entities"]["seller_ids"][:3]
    payload["affected_entities"]["payment_ids"] = payload["affected_entities"]["payment_ids"][:5]
    payload["customer_context"]["related_order_ids"] = payload["customer_context"]["related_order_ids"][:5]
    payload["product_context"]["product_ids"] = payload["product_context"]["product_ids"][:5]
    payload["product_context"]["category_names"] = payload["product_context"]["category_names"][:5]
    payload["root_cause_analysis"]["ranked_causes"] = payload["root_cause_analysis"]["ranked_causes"][:3]
    payload["root_cause_analysis"]["responsible_parties"] = payload["root_cause_analysis"]["responsible_parties"][:3]
    payload["evidence_ids"] = payload["evidence_ids"][:20]
    payload["resolution_actions"] = payload["resolution_actions"][:5]
    return payload
