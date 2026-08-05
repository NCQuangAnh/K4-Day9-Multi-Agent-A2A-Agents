import json
from typing import Any, Dict, List

import pandas as pd

from llm_agent import LLMClient


def _build_delivery_prompt(
    claimed_order_id: str,
    order: Dict[str, Any],
    items: pd.DataFrame,
) -> str:
    return (
        "You are a Delivery Agent. Analyze delivery timestamps and seller handoff. "
        "Return valid JSON with keys: delivered_at, estimated_delivery_at, carrier_handoff_at, delivery_variance_hours, seller_handoff_analysis, late_handoff_seller_ids.\n"
        f"Order data: {json.dumps({k: v for k, v in order.items() if v is not None}, default=str)}\n"
        f"Items: {json.dumps(items.dropna(axis=1, how='all').to_dict(orient='records'), default=str)}\n"
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


def build_delivery_analysis(
    order: Dict[str, Any],
    items: pd.DataFrame,
    llm_client: LLMClient,
) -> Dict[str, Any]:
    delivered_at = order.get("order_delivered_customer_date")
    estimated_at = order.get("order_estimated_delivery_date")
    carrier_handoff_at = order.get("order_delivered_carrier_date")

    if pd.isna(delivered_at):
        delivered_at = None
    if pd.isna(estimated_at):
        estimated_at = None
    if pd.isna(carrier_handoff_at):
        carrier_handoff_at = None

    delivery_variance_hours = None
    if delivered_at is not None and estimated_at is not None:
        delivery_variance_hours = (delivered_at - estimated_at).total_seconds() / 3600.0

    seller_handoff_analysis: List[Dict[str, Any]] = []
    late_handoff_seller_ids: List[str] = []
    if not items.empty and carrier_handoff_at is not None:
        seller_groups = items.groupby("seller_id")
        for seller_id, group in seller_groups:
            shipping_limit_at = group["shipping_limit_date"].min()
            if pd.isna(shipping_limit_at):
                shipping_limit_at = None
            handoff_variance_hours = None
            late_handoff = None
            if shipping_limit_at is not None:
                handoff_variance_hours = (carrier_handoff_at - shipping_limit_at).total_seconds() / 3600.0
                late_handoff = handoff_variance_hours > 0
                if late_handoff:
                    late_handoff_seller_ids.append(seller_id)
            seller_handoff_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": handoff_variance_hours,
                    "late_handoff": late_handoff,
                }
            )

    result = {
        "delivered_at": delivered_at,
        "estimated_delivery_at": estimated_at,
        "carrier_handoff_at": carrier_handoff_at,
        "delivery_variance_hours": delivery_variance_hours,
        "seller_handoff_analysis": seller_handoff_analysis,
        "late_handoff_seller_ids": late_handoff_seller_ids,
    }
    prompt = _build_delivery_prompt(claimed_order_id, order, items)
    model_result = llm_client.generate_json(prompt)
    if model_result:
        result.update({k: model_result.get(k, result[k]) for k in result})
    return result
    delivered_at = order.get("order_delivered_customer_date")
    estimated_at = order.get("order_estimated_delivery_date")
    carrier_handoff_at = order.get("order_delivered_carrier_date")

    if pd.isna(delivered_at):
        delivered_at = None
    if pd.isna(estimated_at):
        estimated_at = None
    if pd.isna(carrier_handoff_at):
        carrier_handoff_at = None

    delivery_variance_hours = None
    if delivered_at is not None and estimated_at is not None:
        delivery_variance_hours = (delivered_at - estimated_at).total_seconds() / 3600.0

    seller_handoff_analysis: List[Dict[str, Any]] = []
    late_handoff_seller_ids: List[str] = []
    if not items.empty and carrier_handoff_at is not None:
        seller_groups = items.groupby("seller_id")
        for seller_id, group in seller_groups:
            shipping_limit_at = group["shipping_limit_date"].min()
            if pd.isna(shipping_limit_at):
                shipping_limit_at = None
            handoff_variance_hours = None
            late_handoff = None
            if shipping_limit_at is not None:
                handoff_variance_hours = (carrier_handoff_at - shipping_limit_at).total_seconds() / 3600.0
                late_handoff = handoff_variance_hours > 0
                if late_handoff:
                    late_handoff_seller_ids.append(seller_id)
            seller_handoff_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": handoff_variance_hours,
                    "late_handoff": late_handoff,
                }
            )

    return {
        "delivered_at": delivered_at,
        "estimated_delivery_at": estimated_at,
        "carrier_handoff_at": carrier_handoff_at,
        "delivery_variance_hours": delivery_variance_hours,
        "seller_handoff_analysis": seller_handoff_analysis,
        "late_handoff_seller_ids": late_handoff_seller_ids,
    }
