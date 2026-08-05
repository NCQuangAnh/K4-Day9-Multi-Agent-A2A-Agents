"""
generate_inputs.py - Generate 50 diverse input cases from real Olist data.
Selects orders covering all primary issue types for comprehensive testing.
"""

import json
import os
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")

os.makedirs(INPUT_DIR, exist_ok=True)

# Load data
orders = pd.read_csv(os.path.join(DATA_DIR, "olist_orders_dataset.csv"))
items = pd.read_csv(os.path.join(DATA_DIR, "olist_order_items_dataset.csv"))
payments = pd.read_csv(os.path.join(DATA_DIR, "olist_order_payments_dataset.csv"))

# Identify order types for diverse selection
# 1. canceled with payment > 0
canceled = orders[orders["order_status"] == "canceled"]["order_id"].tolist()
canceled_paid = []
for oid in canceled:
    p = payments[payments["order_id"] == oid]["payment_value"].sum()
    if p > 0:
        canceled_paid.append(oid)
        if len(canceled_paid) >= 5:
            break

# 2. unavailable with payment > 0
unavail = orders[orders["order_status"] == "unavailable"]["order_id"].tolist()
unavail_paid = []
for oid in unavail:
    p = payments[payments["order_id"] == oid]["payment_value"].sum()
    if p > 0:
        unavail_paid.append(oid)
        if len(unavail_paid) >= 5:
            break

# 3. late delivery (delivered after estimated)
delivered = orders[orders["order_status"] == "delivered"].copy()
delivered = delivered.dropna(subset=["order_delivered_customer_date", "order_estimated_delivery_date"])
delivered["late"] = delivered["order_delivered_customer_date"] > delivered["order_estimated_delivery_date"]
late_orders = delivered[delivered["late"]]["order_id"].tolist()

# Split into late_seller and late_logistics
late_seller_ids = []
late_logistics_ids = []
for oid in late_orders:
    if len(late_seller_ids) >= 10 and len(late_logistics_ids) >= 10:
        break
    oi = items[items["order_id"] == oid]
    if oi.empty:
        continue
    order_row = orders[orders["order_id"] == oid].iloc[0]
    carrier_date = pd.to_datetime(order_row["order_delivered_carrier_date"], errors="coerce")
    if pd.isna(carrier_date):
        continue
    has_late_seller = False
    for _, item_row in oi.iterrows():
        limit = pd.to_datetime(item_row["shipping_limit_date"], errors="coerce")
        if pd.notna(limit) and carrier_date > limit:
            has_late_seller = True
            break
    if has_late_seller and len(late_seller_ids) < 10:
        late_seller_ids.append(oid)
    elif not has_late_seller and len(late_logistics_ids) < 10:
        late_logistics_ids.append(oid)

# 4. split payment (2+ payment rows, reconciled)
payment_counts = payments.groupby("order_id").size()
multi_pay = payment_counts[payment_counts >= 2].index.tolist()

# Filter: on-time delivery + reconciled
split_payment_ids = []
for oid in multi_pay:
    if len(split_payment_ids) >= 10:
        break
    order_row = orders[orders["order_id"] == oid]
    if order_row.empty:
        continue
    order_row = order_row.iloc[0]
    if order_row["order_status"] != "delivered":
        continue
    # Check on-time
    del_date = str(order_row.get("order_delivered_customer_date", ""))
    est_date = str(order_row.get("order_estimated_delivery_date", ""))
    if del_date > est_date and del_date != "nan" and est_date != "nan":
        continue  # late, skip
    # Check reconciled
    oi = items[items["order_id"] == oid]
    if oi.empty:
        continue
    item_total = oi["price"].sum() + oi["freight_value"].sum()
    pay_total = payments[payments["order_id"] == oid]["payment_value"].sum()
    if abs(pay_total - item_total) <= 0.10:
        split_payment_ids.append(oid)

# 5. unsupported_late_claim (on-time, single payment, reconciled)
unsupported_ids = []
single_pay = payment_counts[payment_counts == 1].index.tolist()
for oid in single_pay:
    if len(unsupported_ids) >= 10:
        break
    order_row = orders[orders["order_id"] == oid]
    if order_row.empty:
        continue
    order_row = order_row.iloc[0]
    if order_row["order_status"] != "delivered":
        continue
    del_date = str(order_row.get("order_delivered_customer_date", ""))
    est_date = str(order_row.get("order_estimated_delivery_date", ""))
    if del_date == "nan" or est_date == "nan":
        continue
    if del_date > est_date:
        continue  # late
    oi = items[items["order_id"] == oid]
    if oi.empty:
        continue
    item_total = oi["price"].sum() + oi["freight_value"].sum()
    pay_total = payments[payments["order_id"] == oid]["payment_value"].sum()
    if abs(pay_total - item_total) <= 0.10:
        unsupported_ids.append(oid)

# Assemble 50 cases
all_ids = []
all_ids.extend(canceled_paid[:5])       # ~5 canceled
all_ids.extend(unavail_paid[:5])         # ~5 unavailable
all_ids.extend(late_seller_ids[:10])     # ~10 late seller
all_ids.extend(late_logistics_ids[:10])  # ~10 late logistics
all_ids.extend(split_payment_ids[:10])   # ~10 split payment
all_ids.extend(unsupported_ids[:10])     # ~10 unsupported

# Fill to 50 if needed
if len(all_ids) < 50:
    remaining = 50 - len(all_ids)
    used = set(all_ids)
    for oid in delivered["order_id"].tolist():
        if oid not in used:
            all_ids.append(oid)
            used.add(oid)
            if len(all_ids) >= 50:
                break

# Trim to 50
all_ids = all_ids[:50]

print(f"Selected {len(all_ids)} orders for input cases")
print(f"  Canceled paid: {len(canceled_paid[:5])}")
print(f"  Unavailable paid: {len(unavail_paid[:5])}")
print(f"  Late seller: {len(late_seller_ids[:10])}")
print(f"  Late logistics: {len(late_logistics_ids[:10])}")
print(f"  Split payment: {len(split_payment_ids[:10])}")
print(f"  Unsupported: {len(unsupported_ids[:10])}")

# Generate input JSON files
for i, oid in enumerate(all_ids, 1):
    case_id = f"EC_{i:03d}"
    case_input = {
        "case_id": case_id,
        "customer_request": {
            "language": "vi",
            "message": "Hay dieu tra khieu nai, kiem tra lich su khach hang va doi soat toan bo order.",
            "claimed_order_id": oid
        },
        "investigation_scope": {
            "include_customer_history": True,
            "include_product_context": True
        },
        "policy_version": "EC_POLICY_V2"
    }
    filepath = os.path.join(INPUT_DIR, f"{case_id}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(case_input, f, ensure_ascii=False, indent=2)

print(f"\nGenerated {len(all_ids)} input files in {INPUT_DIR}")
