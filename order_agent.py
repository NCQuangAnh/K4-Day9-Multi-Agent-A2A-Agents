import json
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from llm_agent import LLMClient


def _build_order_prompt(
    claimed_order_id: str,
    order: pd.Series,
    items: pd.DataFrame,
    products: pd.DataFrame,
    sellers: pd.DataFrame,
) -> str:
    return (
        "You are an Order Agent. Analyze the provided order details and related items, products, and sellers. "
        "Return JSON with keys: item_ids, seller_ids, product_ids, category_names. Do not invent values.\n"
        f"Order: {json.dumps(order.dropna().to_dict(), default=str)}\n"
        f"Items: {json.dumps(items.dropna(axis=1, how='all').to_dict(orient='records'), default=str)}\n"
        f"Products: {json.dumps(products.dropna(axis=1, how='all').to_dict(orient='records'), default=str)}\n"
        f"Sellers: {json.dumps(sellers.dropna(axis=1, how='all').to_dict(orient='records'), default=str)}\n"
        "Output only JSON."
    )


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def build_order_context(
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
    products: pd.DataFrame,
    sellers: pd.DataFrame,
    claimed_order_id: str,
    llm_client: LLMClient,
) -> Dict[str, Any]:
    order_row = orders.loc[orders["order_id"] == claimed_order_id]
    if order_row.empty:
        return {
            "order": {},
            "item_ids": [],
            "seller_ids": [],
            "product_ids": [],
            "category_names": [],
            "items": pd.DataFrame(),
        }

    order_items_rows = order_items.loc[order_items["order_id"] == claimed_order_id]
    product_ids = order_items_rows["product_id"].astype(str).unique().tolist()
    seller_ids = order_items_rows["seller_id"].astype(str).unique().tolist()

    categorizations = products.loc[products["product_id"].isin(product_ids)]
    category_names = categorizations["product_category_name"].astype(str).unique().tolist()

    item_ids = [f"{claimed_order_id}:{int(item_id)}" for item_id in order_items_rows["order_item_id"].astype(int).tolist()]

    prompt = _build_order_prompt(
        claimed_order_id,
        order_row.iloc[0],
        order_items_rows,
        categorizations,
        sellers.loc[sellers["seller_id"].isin(seller_ids)] if seller_ids else pd.DataFrame(),
    )
    model_output = llm_client.generate_json(prompt)
    if model_output is not None:
        return {
            "order": order_row.iloc[0].to_dict(),
            "item_ids": model_output.get("item_ids", item_ids),
            "seller_ids": model_output.get("seller_ids", seller_ids),
            "product_ids": model_output.get("product_ids", product_ids),
            "category_names": model_output.get("category_names", category_names),
            "items": order_items_rows,
        }

    return {
        "order": order_row.iloc[0].to_dict(),
        "item_ids": item_ids,
        "seller_ids": seller_ids,
        "product_ids": product_ids,
        "category_names": category_names,
        "items": order_items_rows,
    }
    order_row = orders.loc[orders["order_id"] == claimed_order_id]
    if order_row.empty:
        return {
            "order": {},
            "item_ids": [],
            "seller_ids": [],
            "product_ids": [],
            "category_names": [],
            "items": pd.DataFrame(),
        }

    order_items_rows = order_items.loc[order_items["order_id"] == claimed_order_id]
    product_ids = order_items_rows["product_id"].astype(str).unique().tolist()
    seller_ids = order_items_rows["seller_id"].astype(str).unique().tolist()

    categorizations = products.loc[products["product_id"].isin(product_ids)]
    category_names = categorizations["product_category_name"].astype(str).unique().tolist()

    payment_item_count = order_items_rows.shape[0]
    item_ids = [f"{claimed_order_id}:{int(item_id)}" for item_id in order_items_rows["order_item_id"].astype(int).tolist()]

    return {
        "order": order_row.iloc[0].to_dict(),
        "item_ids": item_ids,
        "seller_ids": seller_ids,
        "product_ids": product_ids,
        "category_names": category_names,
        "items": order_items_rows,
    }
