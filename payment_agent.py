import json
from typing import Dict, Any

import pandas as pd

from llm_agent import LLMClient


def _build_payment_prompt(
    claimed_order_id: str,
    order_items: pd.DataFrame,
    payments_rows: pd.DataFrame,
) -> str:
    return (
        "You are a Payment Agent. Using only the provided order item and payment rows, "
        "return valid JSON with keys: item_total_brl, freight_total_brl, expected_total_brl, payment_total_brl, difference_brl, reconciled, payment_types, payment_ids.\n"
        f"Order items: {json.dumps(order_items.dropna(axis=1, how='all').to_dict(orient='records'), default=str)}\n"
        f"Payments: {json.dumps(payments_rows.dropna(axis=1, how='all').to_dict(orient='records'), default=str)}\n"
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


def build_payment_analysis(
    order_items: pd.DataFrame,
    payments: pd.DataFrame,
    claimed_order_id: str,
    llm_client: LLMClient,
) -> Dict[str, Any]:
    payments_rows = payments.loc[payments["order_id"] == claimed_order_id]
    if order_items.empty:
        result = {
            "currency": "BRL",
            "item_total_brl": None,
            "freight_total_brl": None,
            "expected_total_brl": None,
            "payment_total_brl": float(payments_rows["payment_value"].sum()) if not payments_rows.empty else 0.0,
            "difference_brl": None,
            "reconciled": None,
            "payment_types": payments_rows["payment_type"].astype(str).tolist(),
            "payment_ids": [f"{claimed_order_id}:{int(seq)}" for seq in payments_rows["payment_sequential"].astype(int).tolist()],
        }
        prompt = _build_payment_prompt(claimed_order_id, order_items, payments_rows)
        model_result = llm_client.generate_json(prompt)
        if model_result:
            result.update({k: model_result.get(k, result[k]) for k in result})
        return result

    item_total = float(order_items["price"].sum())
    freight_total = float(order_items["freight_value"].sum())
    expected_total = item_total + freight_total
    payment_total = float(payments_rows["payment_value"].sum())
    difference = payment_total - expected_total
    reconciled = abs(difference) <= 0.10
    result = {
        "currency": "BRL",
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected_total,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": reconciled,
        "payment_types": payments_rows["payment_type"].astype(str).tolist(),
        "payment_ids": [f"{claimed_order_id}:{int(seq)}" for seq in payments_rows["payment_sequential"].astype(int).tolist()],
    }
    prompt = _build_payment_prompt(claimed_order_id, order_items, payments_rows)
    model_result = llm_client.generate_json(prompt)
    if model_result:
        result.update({k: model_result.get(k, result[k]) for k in result})
    return result
    if order_items.empty:
        return {
            "currency": "BRL",
            "item_total_brl": None,
            "freight_total_brl": None,
            "expected_total_brl": None,
            "payment_total_brl": float(payments_rows["payment_value"].sum()) if not payments_rows.empty else 0.0,
            "difference_brl": None,
            "reconciled": None,
            "payment_types": payments_rows["payment_type"].astype(str).tolist(),
            "payment_ids": [f"{claimed_order_id}:{int(seq)}" for seq in payments_rows["payment_sequential"].astype(int).tolist()],
        }

    item_total = float(order_items["price"].sum())
    freight_total = float(order_items["freight_value"].sum())
    expected_total = item_total + freight_total
    payment_total = float(payments_rows["payment_value"].sum())
    difference = payment_total - expected_total
    reconciled = abs(difference) <= 0.10

    return {
        "currency": "BRL",
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected_total,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": reconciled,
        "payment_types": payments_rows["payment_type"].astype(str).tolist(),
        "payment_ids": [f"{claimed_order_id}:{int(seq)}" for seq in payments_rows["payment_sequential"].astype(int).tolist()],
    }
