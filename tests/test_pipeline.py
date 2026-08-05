import json
import pytest
from pathlib import Path
from pipeline import load_data, build_output, compute_amounts

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def test_load_data_has_orders():
    data = load_data()
    assert "orders" in data
    assert len(data["orders"]) > 0


def test_compute_amounts_reconciled():
    items = [{"price": "50.00", "freight_value": "10.00"}, {"price": "20.00", "freight_value": "5.00"}]
    payments = [{"payment_value": "40.00"}, {"payment_value": "45.00"}]
    result = compute_amounts("oid", items, payments)
    assert result["item_total_brl"] == 70
    assert result["freight_total_brl"] == 15
    assert result["expected_total_brl"] == 85
    assert result["payment_total_brl"] == 85
    assert result["difference_brl"] == 0
    assert result["reconciled"] is True


def test_build_output_sample_order():
    data = load_data()
    case = {
        "case_id": "EC_SAMPLE",
        "customer_request": {
            "language": "vi",
            "message": "Hãy điều tra khiếu nại.",
            "claimed_order_id": "f31535f21d145b2345e2bf7f09d62322",
        },
        "investigation_scope": {
            "include_customer_history": True,
            "include_product_context": True,
        },
        "policy_version": "EC_POLICY_V2",
    }
    output = build_output(case, data)
    assert output["case_id"] == "EC_SAMPLE"
    assert output["case_assessment"]["primary_issue"] in {
        "late_delivery_seller",
        "late_delivery_logistics",
        "valid_split_payment",
        "unsupported_late_claim",
        "canceled_order_paid",
        "unavailable_order_paid",
    }
    assert output["affected_entities"]["order_ids"] == ["f31535f21d145b2345e2bf7f09d62322"]
    assert output["payment_reconciliation"]["currency"] == "BRL"
    assert isinstance(output["resolution_actions"], list)
