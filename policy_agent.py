import json
from typing import Any, Dict, List

from llm_agent import LLMClient


def _build_policy_prompt(
    claimed_order_id: str,
    order: Dict[str, Any],
    payment_analysis: Dict[str, Any],
    delivery_analysis: Dict[str, Any],
) -> str:
    return (
        "You are a Policy Agent. Apply EC_POLICY_V2 based on the provided order status, payments, and delivery analysis. "
        "Return valid JSON with keys: primary_issue, case_status, recommended_refund, responsible_party_type, responsible_party_id, action, cause_code.\n"
        f"Order data: {json.dumps({k: v for k, v in order.items() if v is not None}, default=str)}\n"
        f"Payment analysis: {json.dumps(payment_analysis, default=str)}\n"
        f"Delivery analysis: {json.dumps(delivery_analysis, default=str)}\n"
        "Output only JSON."
    )


def _parse_json(text: str) -> Dict[str, Any]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON found")
        return json.loads(text[start : end + 1])
    except Exception:
        return {}


def choose_primary_issue(
    order: Dict[str, Any],
    payment_analysis: Dict[str, Any],
    delivery_analysis: Dict[str, Any],
    items: Any,
    llm_client: LLMClient,
) -> Dict[str, Any]:
    prompt = _build_policy_prompt("unknown", order, payment_analysis, delivery_analysis)
    model_result = llm_client.generate_json(prompt)
    if model_result:
        return {
            "primary_issue": model_result.get("primary_issue", "unsupported_late_claim"),
            "case_status": model_result.get("case_status", "no_action"),
            "recommended_refund": model_result.get("recommended_refund", 0.0),
            "responsible_party_type": model_result.get("responsible_party_type"),
            "responsible_party_id": model_result.get("responsible_party_id"),
            "action": model_result.get("action", "reject_late_refund"),
            "cause_code": model_result.get("cause_code", "DELIVERY_WITHIN_ESTIMATE"),
        }

    status = order.get("order_status")
    payment_total = payment_analysis.get("payment_total_brl", 0.0)
    expected_total = payment_analysis.get("expected_total_brl")
    difference = payment_analysis.get("difference_brl")

    delivered_at = delivery_analysis.get("delivered_at")
    estimated_at = delivery_analysis.get("estimated_delivery_at")
    late_delivery = False
    if delivered_at is not None and estimated_at is not None:
        late_delivery = delivered_at > estimated_at

    late_handoff_seller_ids = delivery_analysis.get("late_handoff_seller_ids", [])

    if status == "canceled" and payment_total > 0:
        return {
            "primary_issue": "canceled_order_paid",
            "case_status": "action_required",
            "recommended_refund": payment_total,
            "responsible_party_type": "platform",
            "responsible_party_id": "OLIST_PLATFORM",
            "action": "issue_full_refund",
            "cause_code": "ORDER_CANCELED_AFTER_PAYMENT",
        }

    if status == "unavailable" and payment_total > 0:
        return {
            "primary_issue": "unavailable_order_paid",
            "case_status": "action_required",
            "recommended_refund": payment_total,
            "responsible_party_type": "platform",
            "responsible_party_id": "OLIST_PLATFORM",
            "action": "issue_full_refund",
            "cause_code": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        }

    if late_delivery and len(late_handoff_seller_ids) > 0:
        freight_total = payment_analysis.get("freight_total_brl", 0.0) or 0.0
        return {
            "primary_issue": "late_delivery_seller",
            "case_status": "action_required",
            "recommended_refund": freight_total,
            "responsible_party_type": "seller",
            "responsible_party_id": late_handoff_seller_ids,
            "action": "refund_freight",
            "cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
        }

    if late_delivery and len(late_handoff_seller_ids) == 0:
        freight_total = payment_analysis.get("freight_total_brl", 0.0) or 0.0
        return {
            "primary_issue": "late_delivery_logistics",
            "case_status": "action_required",
            "recommended_refund": freight_total,
            "responsible_party_type": "logistics_provider",
            "responsible_party_id": "LOGISTICS_PROVIDER",
            "action": "refund_freight",
            "cause_code": "CARRIER_DELIVERED_AFTER_ESTIMATE",
        }

    if payment_analysis.get("payment_ids") and expected_total is not None and abs(difference or 0.0) <= 0.10 and len(payment_analysis.get("payment_ids", [])) >= 2:
        return {
            "primary_issue": "valid_split_payment",
            "case_status": "no_action",
            "recommended_refund": 0.0,
            "responsible_party_type": None,
            "responsible_party_id": None,
            "action": "explain_valid_split_payment",
            "cause_code": "MULTIPLE_PAYMENTS_RECONCILED",
        }

    if not late_delivery and expected_total is not None and abs(difference or 0.0) <= 0.10:
        return {
            "primary_issue": "unsupported_late_claim",
            "case_status": "no_action",
            "recommended_refund": 0.0,
            "responsible_party_type": None,
            "responsible_party_id": None,
            "action": "reject_late_refund",
            "cause_code": "DELIVERY_WITHIN_ESTIMATE",
        }

    return {
        "primary_issue": "unsupported_late_claim",
        "case_status": "no_action",
        "recommended_refund": 0.0,
        "responsible_party_type": None,
        "responsible_party_id": None,
        "action": "reject_late_refund",
        "cause_code": "DELIVERY_WITHIN_ESTIMATE",
    }


def build_secondary_issues(order_items: Any, payments: Any, customer_unique_id: str, orders: Any, claimed_order_id: str) -> List[str]:
    issues = []
    if not order_items.empty and order_items.shape[0] >= 2:
        issues.append("multi_item_order")
    if not order_items.empty and order_items["seller_id"].nunique() >= 2:
        issues.append("multi_seller_order")
    if payments is not None and payments.shape[0] >= 2:
        issues.append("split_payment")
    if customer_unique_id is not None:
        repeat_orders = orders.loc[
            (orders["customer_id"] == orders.loc[orders["order_id"] == claimed_order_id, "customer_id"].iloc[0])
            & (orders["order_id"] != claimed_order_id)
        ]
        if not repeat_orders.empty:
            issues.append("repeat_customer")
    if not order_items.empty:
        if order_items["product_id"].nunique() >= 2:
            issues.append("multiple_categories")
    return issues


def build_root_cause_analysis(primary: Dict[str, Any], responsible_party_ids: List[str]) -> Dict[str, Any]:
    causes = [{"cause_code": primary["cause_code"], "rank": 1}]
    responsible_parties = []
    if primary["responsible_party_type"] is not None:
        if isinstance(responsible_party_ids, list):
            for party_id in responsible_party_ids:
                responsible_parties.append(
                    {"party_type": primary["responsible_party_type"], "party_id": party_id}
                )
        else:
            responsible_parties.append(
                {"party_type": primary["responsible_party_type"], "party_id": responsible_party_ids}
            )
    return {
        "ranked_causes": causes,
        "responsible_parties": responsible_parties,
    }


def build_resolution_actions(primary: Dict[str, Any]) -> List[str]:
    actions = [primary["action"]]
    if primary["action"] == "refund_freight":
        if primary["cause_code"] == "SELLER_HANDOFF_AFTER_LIMIT":
            actions.append("review_seller_handoff")
        else:
            actions.append("review_carrier_delay")
    if primary["action"] != "explain_valid_split_payment":
        if primary["action"] != "reject_late_refund":
            actions.append("verify_refund_completion")
        actions.append("verify_payment_allocation")
    return actions
