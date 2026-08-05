import csv
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"

CSV_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_datetime(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        return None


def decimal(value: str | float | int | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def quantize(value: Decimal | None, places: int = 2) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(f"1.{'0'*places}"), rounding=ROUND_HALF_UP)


def load_csv(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / CSV_FILES[name]
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def index_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        index.setdefault(row[key], []).append(row)
    return index


def load_data() -> dict[str, Any]:
    customers = load_csv("customers")
    orders = load_csv("orders")
    items = load_csv("items")
    payments = load_csv("payments")
    products = load_csv("products")
    sellers = load_csv("sellers")
    customers_by_id = {row["customer_id"]: row for row in customers}
    orders_by_customer_unique: dict[str, list[dict[str, str]]] = {}
    for order in orders:
        customer = customers_by_id.get(order["customer_id"])
        if customer:
            orders_by_customer_unique.setdefault(customer["customer_unique_id"], []).append(order)
    return {
        "customers": index_by(customers, "customer_id"),
        "orders_by_customer_unique": orders_by_customer_unique,
        "orders": index_by(orders, "order_id"),
        "items": index_by(items, "order_id"),
        "payments": index_by(payments, "order_id"),
        "products": {row["product_id"]: row for row in products},
        "sellers": {row["seller_id"]: row for row in sellers},
    }


def compute_amounts(order_id: str, items: list[dict[str, str]], payments: list[dict[str, str]]) -> dict[str, Any]:
    item_total = quantize(sum((decimal(row["price"]) or Decimal(0) for row in items), Decimal(0)))
    freight_total = quantize(sum((decimal(row["freight_value"]) or Decimal(0) for row in items), Decimal(0)))
    payment_total = quantize(sum((decimal(row["payment_value"]) or Decimal(0) for row in payments), Decimal(0)))
    expected_total = None if not items else quantize(item_total + freight_total)
    difference = None if expected_total is None else quantize(payment_total - expected_total)
    reconciled = None if difference is None else abs(difference) <= Decimal("0.10")
    return {
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected_total,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": reconciled,
    }


def build_evidence(order_id: str, items: list[dict[str, str]], payments: list[dict[str, str]], responsible_sellers: list[str], root_cause: str) -> list[str]:
    evidence = [f"order:{order_id}"]
    evidence.extend(f"item:{order_id}:{item['order_item_id']}" for item in items[:5])
    evidence.extend(f"payment:{order_id}:{p['payment_sequential']}" for p in payments[:5])
    evidence.extend(f"seller:{sid}" for sid in responsible_sellers[:3])
    evidence.append(f"policy:{root_cause}")
    return evidence[:20]


def select_primary_issue(order: dict[str, str], amount_info: dict[str, Any], delivery_diff_hours: float | None, late_handoff: bool, late_handoff_sellers: list[str], payments: list[dict[str, str]]) -> tuple[str, str, list[dict[str, str]], str]:
    status = order.get("order_status")
    total_payment = amount_info["payment_total_brl"] or Decimal(0)
    expected_total = amount_info["expected_total_brl"]
    if status == "canceled" and total_payment > 0:
        return "canceled_order_paid", "issue_full_refund", [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}], "ORDER_CANCELED_AFTER_PAYMENT"
    if status == "unavailable" and total_payment > 0:
        return "unavailable_order_paid", "issue_full_refund", [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}], "ORDER_UNAVAILABLE_AFTER_PAYMENT"
    if delivery_diff_hours is not None and delivery_diff_hours > 0 and late_handoff:
        return "late_delivery_seller", "refund_freight", [{"party_type": "seller", "party_id": seller_id} for seller_id in late_handoff_sellers], "SELLER_HANDOFF_AFTER_LIMIT"
    if delivery_diff_hours is not None and delivery_diff_hours > 0:
        return "late_delivery_logistics", "refund_freight", [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}], "CARRIER_DELIVERED_AFTER_ESTIMATE"
    if len(payments) >= 2 and expected_total is not None and amount_info["reconciled"]:
        return "valid_split_payment", "explain_valid_split_payment", [], "MULTIPLE_PAYMENTS_RECONCILED"
    return "unsupported_late_claim", "reject_late_refund", [], "DELIVERY_WITHIN_ESTIMATE"


def build_secondary_issues(items: list[dict[str, str]], payments: list[dict[str, str]], customer_orders: list[dict[str, str]], products: dict[str, dict[str, str]]) -> list[str]:
    issues: list[str] = []
    if len(items) >= 2:
        issues.append("multi_item_order")
    if len({item["seller_id"] for item in items}) >= 2:
        issues.append("multi_seller_order")
    if len(payments) >= 2:
        issues.append("split_payment")
    if customer_orders:
        issues.append("repeat_customer")
    if len({products[item["product_id"]]["product_category_name"] for item in items if item["product_id"] in products}) >= 2:
        issues.append("multiple_categories")
    return issues


def build_delivery_analysis(order: dict[str, str], items: list[dict[str, str]]) -> dict[str, Any]:
    delivered_at = order.get("order_delivered_customer_date")
    estimated_at = order.get("order_estimated_delivery_date")
    carrier_at = order.get("order_delivered_carrier_date")
    delivered_dt = parse_datetime(delivered_at)
    estimated_dt = parse_datetime(estimated_at)
    carrier_dt = parse_datetime(carrier_at)
    variance = None
    if delivered_dt and estimated_dt:
        variance = round((delivered_dt - estimated_dt).total_seconds() / 3600, 2)
    seller_analysis = []
    late_sellers: list[str] = []
    if items:
        by_seller: dict[str, list[dict[str, str]]] = {}
        for item in items:
            by_seller.setdefault(item["seller_id"], []).append(item)
        for seller_id, seller_items in by_seller.items():
            shipping_limits = [item["shipping_limit_date"] for item in seller_items if parse_datetime(item.get("shipping_limit_date"))]
            shipping_limit_at = min(shipping_limits, key=lambda value: parse_datetime(value) or datetime.max) if shipping_limits else None
            shipping_limit = parse_datetime(shipping_limit_at)
            if carrier_dt and shipping_limit:
                handoff_var = round((carrier_dt - shipping_limit).total_seconds() / 3600, 2)
                late = handoff_var > 0
                seller_analysis.append({
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": handoff_var,
                    "late_handoff": late,
                })
                if late:
                    late_sellers.append(seller_id)
    return {
        "delivered_at": delivered_at or None,
        "estimated_delivery_at": estimated_at or None,
        "carrier_handoff_at": carrier_at or None,
        "delivery_variance_hours": variance,
        "seller_handoff_analysis": seller_analysis,
        "late_handoff_seller_ids": late_sellers[:3],
    }


def build_output(case: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    order_id = case["customer_request"]["claimed_order_id"]
    order_rows = data["orders"].get(order_id, [])
    if not order_rows:
        raise ValueError(f"Order {order_id} not found")
    order = order_rows[0]
    items = data["items"].get(order_id, [])
    payments = data["payments"].get(order_id, [])
    customer = data["customers"].get(order["customer_id"], [{}])[0]
    amount_info = compute_amounts(order_id, items, payments)
    delivery = build_delivery_analysis(order, items)
    late_handoff = len(delivery["late_handoff_seller_ids"]) > 0
    primary_issue, action_main, responsible_parties, root_cause = select_primary_issue(
        order, amount_info, delivery["delivery_variance_hours"], late_handoff, delivery["late_handoff_seller_ids"], payments,
    )
    customer_orders = [row for row in data["orders_by_customer_unique"].get(customer.get("customer_unique_id"), []) if row["order_id"] != order_id]
    secondary_issues = build_secondary_issues(items, payments, customer_orders, data["products"])
    category_names = list(dict.fromkeys(data["products"][item["product_id"]]["product_category_name"] for item in items if item["product_id"] in data["products"]))[:5]
    product_ids = list(dict.fromkeys(item["product_id"] for item in items))[:5]
    actions = [action_main]
    if primary_issue in {"canceled_order_paid", "unavailable_order_paid"}:
        actions.append("verify_refund_completion")
    elif primary_issue == "late_delivery_seller":
        actions.extend(["review_seller_handoff", "verify_refund_completion"])
    elif primary_issue == "late_delivery_logistics":
        actions.extend(["review_carrier_delay", "verify_refund_completion"])
    if "multi_seller_order" in secondary_issues:
        actions.append("coordinate_multi_seller_case")
    if "split_payment" in secondary_issues and primary_issue != "valid_split_payment":
        actions.append("verify_payment_allocation")
    output = {
        "case_id": case["case_id"],
        "case_assessment": {
            "primary_issue": primary_issue,
            "secondary_issues": secondary_issues,
            "case_status": "action_required" if primary_issue not in {"valid_split_payment", "unsupported_late_claim"} else "no_action" if primary_issue == "valid_split_payment" else "no_action",
            "confidence": 0.92,
        },
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": [f"{order_id}:{item['order_item_id']}" for item in items][:5],
            "seller_ids": list(dict.fromkeys(item["seller_id"] for item in items))[:3],
            "payment_ids": [f"{order_id}:{p['payment_sequential']}" for p in payments][:5],
        },
        "customer_context": {
            "customer_unique_id": customer.get("customer_unique_id"),
            "related_order_ids": [row["order_id"] for row in customer_orders][:5],
        },
        "product_context": {
            "product_ids": product_ids,
            "category_names": category_names,
        },
        "delivery_analysis": delivery,
        "payment_reconciliation": {
            "currency": "BRL",
            "item_total_brl": amount_info["item_total_brl"],
            "freight_total_brl": amount_info["freight_total_brl"],
            "expected_total_brl": amount_info["expected_total_brl"],
            "payment_total_brl": amount_info["payment_total_brl"],
            "difference_brl": amount_info["difference_brl"],
            "reconciled": amount_info["reconciled"],
            "payment_types": [p["payment_type"] for p in payments][:5],
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": root_cause, "rank": 1}],
            "responsible_parties": responsible_parties[:3],
        },
        "evidence_ids": build_evidence(order_id, items, payments, [party["party_id"] for party in responsible_parties if party["party_type"] == "seller"], root_cause),
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": amount_info["freight_total_brl"] if primary_issue in {"late_delivery_seller", "late_delivery_logistics"} else (amount_info["payment_total_brl"] if primary_issue in {"canceled_order_paid", "unavailable_order_paid"} else Decimal("0.00")),
        },
        "resolution_actions": actions,
    }
    output["resolution_actions"] = [a for a in output["resolution_actions"] if a]
    return output


def process_all_cases() -> None:
    data = load_data()
    OUTPUT_DIR.mkdir(exist_ok=True)
    for case_file in sorted(INPUT_DIR.glob("*.json")):
        with case_file.open("r", encoding="utf-8") as f:
            case = json.load(f)
        output = build_output(case, data)
        out_path = OUTPUT_DIR / case_file.name
        def _json_default(o):
            if isinstance(o, Decimal):
                return float(o)
            raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

        with out_path.open("w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=_json_default)


if __name__ == "__main__":
    process_all_cases()
