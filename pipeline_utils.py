import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"

DATE_COLUMNS = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
    "shipping_limit_date",
]


def load_csv(name: str, parse_dates: Optional[List[str]] = None) -> pd.DataFrame:
    path = DATA_DIR / name
    if parse_dates is None:
        parse_dates = []
    return pd.read_csv(path, parse_dates=parse_dates)


def load_all_data() -> Dict[str, pd.DataFrame]:
    return {
        "orders": load_csv("olist_orders_dataset.csv", parse_dates=[
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ]),
        "order_items": load_csv("olist_order_items_dataset.csv", parse_dates=["shipping_limit_date"]),
        "payments": load_csv("olist_order_payments_dataset.csv"),
        "customers": load_csv("olist_customers_dataset.csv"),
        "products": load_csv("olist_products_dataset.csv"),
        "sellers": load_csv("olist_sellers_dataset.csv"),
        "category_translation": load_csv("product_category_name_translation.csv"),
    }


def safe_round(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float(round(value, digits))


def normalize_list(values: List[Any], limit: int) -> List[Any]:
    return values[:limit]


def format_timestamp(value: Any) -> Optional[str]:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def load_case(case_path: Path) -> Dict[str, Any]:
    with case_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_case_output(case_id: str, payload: Dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{case_id}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def build_evidence_id(kind: str, *parts: Any) -> str:
    joined = ":".join(str(p) for p in parts)
    return f"{kind}:{joined}"
