import json
from typing import Dict, List, Optional

import pandas as pd

from llm_agent import LLMClient


def _build_customer_prompt(
    claimed_order_id: str,
    order_row: pd.Series,
    customer_row: pd.Series,
    related_order_ids: List[str],
) -> str:
    return (
        "You are a Customer Agent. Analyze the provided order and customer data, "
        "then return valid JSON with keys: customer_unique_id and related_order_ids.\n"
        "Do not invent values. Only use values from the data below.\n"
        f"Order ID: {claimed_order_id}\n"
        f"Order fields: {json.dumps(order_row.dropna().to_dict(), default=str)}\n"
        f"Customer fields: {json.dumps(customer_row.dropna().to_dict(), default=str)}\n"
        f"Related order IDs: {json.dumps(related_order_ids)}\n"
        "Output only JSON."
    )


def _parse_json(text: str) -> Optional[Dict[str, List[str]]]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        payload = json.loads(text[start : end + 1])
        return {
            "customer_unique_id": payload.get("customer_unique_id"),
            "related_order_ids": payload.get("related_order_ids", []),
        }
    except json.JSONDecodeError:
        return None


def build_customer_context(
    orders: pd.DataFrame,
    customers: pd.DataFrame,
    claimed_order_id: str,
    include_history: bool,
    llm_client: LLMClient,
) -> Dict[str, Optional[List[str]]]:
    order_row = orders.loc[orders["order_id"] == claimed_order_id]
    if order_row.empty:
        return {"customer_unique_id": None, "related_order_ids": []}

    customer_id = order_row.iloc[0]["customer_id"]
    customer_row = customers.loc[customers["customer_id"] == customer_id]
    if customer_row.empty:
        return {"customer_unique_id": None, "related_order_ids": []}

    related_order_ids: List[str] = []
    if include_history:
        related_orders = orders.loc[
            (orders["customer_id"] == customer_id)
            & (orders["order_id"] != claimed_order_id)
        ]
        related_order_ids = related_orders["order_id"].astype(str).tolist()

    prompt = _build_customer_prompt(
        claimed_order_id,
        order_row.iloc[0],
        customer_row.iloc[0],
        related_order_ids,
    )
    model_result = llm_client.generate_json(prompt)
    if model_result and model_result.get("customer_unique_id") is not None:
        return {
            "customer_unique_id": model_result["customer_unique_id"],
            "related_order_ids": model_result.get("related_order_ids", []),
        }

    return {
        "customer_unique_id": customer_row.iloc[0]["customer_unique_id"],
        "related_order_ids": related_order_ids,
    }
