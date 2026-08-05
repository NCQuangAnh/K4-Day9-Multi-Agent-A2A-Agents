import json
from pathlib import Path
from typing import Any, Dict

from customer_agent import build_customer_context
from delivery_agent import build_delivery_analysis
from llm_agent import LLMClient
from order_agent import build_order_context
from payment_agent import build_payment_analysis
from policy_agent import build_resolution_actions, build_root_cause_analysis, build_secondary_issues, choose_primary_issue
from pipeline_utils import (
    DATA_DIR,
    INPUT_DIR,
    OUTPUT_DIR,
    build_evidence_id,
    format_timestamp,
    load_all_data,
    load_case,
    safe_round,
    write_case_output,
)
from verifier_agent import enforce_limits, validate_output_schema


def process_case(case_path: Path, data: Dict[str, Any], orders_df: Any, llm_client: LLMClient) -> Dict[str, Any]:
    case = load_case(case_path)
    case_id = case["case_id"]
    claimed_order_id = case["customer_request"]["claimed_order_id"]
    include_history = case["investigation_scope"]["include_customer_history"]
    include_product_context = case["investigation_scope"]["include_product_context"]

    customer_context = build_customer_context(
        data["orders"], data["customers"], claimed_order_id, include_history, llm_client
    )
    order_context = build_order_context(
        data["orders"], data["order_items"], data["products"], data["sellers"], claimed_order_id, llm_client
    )
    payment_analysis = build_payment_analysis(order_context["items"], data["payments"], claimed_order_id, llm_client)
    delivery_analysis = build_delivery_analysis(order_context["order"], order_context["items"], llm_client)
    primary = choose_primary_issue(
        order_context["order"], payment_analysis, delivery_analysis, order_context["items"], llm_client
    )
    secondary_issues = build_secondary_issues(
        order_context["items"], data["payments"].loc[data["payments"]["order_id"] == claimed_order_id], customer_context["customer_unique_id"], data["orders"], claimed_order_id
    )
    evidence_ids = [build_evidence_id("order", claimed_order_id)]
    for item_id in order_context["item_ids"]:
        parts = item_id.split(":")
        evidence_ids.append(build_evidence_id("item", *parts))
    for payment_id in payment_analysis["payment_ids"]:
        parts = payment_id.split(":")
        evidence_ids.append(build_evidence_id("payment", *parts))
    for seller_id in order_context["seller_ids"]:
        evidence_ids.append(build_evidence_id("seller", seller_id))
    evidence_ids.append(build_evidence_id("policy", primary["cause_code"]))

    output = {
        "case_id": case_id,
        "case_assessment": {
            "primary_issue": primary["primary_issue"],
            "secondary_issues": secondary_issues,
            "case_status": primary["case_status"],
            "confidence": 0.92,
        },
        "affected_entities": {
            "order_ids": [claimed_order_id],
            "item_ids": order_context["item_ids"],
            "seller_ids": order_context["seller_ids"],
            "payment_ids": payment_analysis["payment_ids"],
        },
        "customer_context": {
            "customer_unique_id": customer_context["customer_unique_id"],
            "related_order_ids": customer_context["related_order_ids"],
        },
        "product_context": {
            "product_ids": order_context["product_ids"] if include_product_context else [],
            "category_names": order_context["category_names"] if include_product_context else [],
        },
        "delivery_analysis": {
            "delivered_at": format_timestamp(delivery_analysis["delivered_at"]),
            "estimated_delivery_at": format_timestamp(delivery_analysis["estimated_delivery_at"]),
            "carrier_handoff_at": format_timestamp(delivery_analysis["carrier_handoff_at"]),
            "delivery_variance_hours": safe_round(delivery_analysis["delivery_variance_hours"]),
            "seller_handoff_analysis": [
                {
                    "seller_id": entry["seller_id"],
                    "shipping_limit_at": format_timestamp(entry["shipping_limit_at"]),
                    "handoff_variance_hours": safe_round(entry["handoff_variance_hours"]),
                    "late_handoff": entry["late_handoff"],
                }
                for entry in delivery_analysis["seller_handoff_analysis"]
            ],
            "late_handoff_seller_ids": delivery_analysis["late_handoff_seller_ids"],
        },
        "payment_reconciliation": {
            "currency": payment_analysis["currency"],
            "item_total_brl": safe_round(payment_analysis["item_total_brl"]),
            "freight_total_brl": safe_round(payment_analysis["freight_total_brl"]),
            "expected_total_brl": safe_round(payment_analysis["expected_total_brl"]),
            "payment_total_brl": safe_round(payment_analysis["payment_total_brl"]),
            "difference_brl": safe_round(payment_analysis["difference_brl"]),
            "reconciled": payment_analysis["reconciled"],
            "payment_types": payment_analysis["payment_types"],
        },
        "root_cause_analysis": build_root_cause_analysis(primary, order_context["seller_ids"]),
        "evidence_ids": evidence_ids,
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": safe_round(primary["recommended_refund"]),
        },
        "resolution_actions": build_resolution_actions(primary),
    }

    output = enforce_limits(output)
    if not validate_output_schema(output):
        raise ValueError("Output schema validation failed")

    write_case_output(case_id, output)
    return output


def main() -> None:
    data = load_all_data()
    orders_df = data["orders"]
    llm_client = LLMClient()
    OUTPUT_DIR.mkdir(exist_ok=True)
    for case_path in sorted(INPUT_DIR.glob("EC_*.json")):
        try:
            result = process_case(case_path, data, orders_df, llm_client)
            print(f"Processed {case_path.name}: {result['case_assessment']['primary_issue']}")
        except Exception as exc:
            print(f"Failed {case_path.name}: {exc}")


if __name__ == "__main__":
    main()
