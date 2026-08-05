# Pipeline Specification — K4 Day 09 Multi-Agent

> `architecture.md` trả lời **ai làm gì và vì sao**.
> Tài liệu này trả lời **chạy ra sao** — từng stage, từng cấu trúc dữ liệu, từng field.
> Đây là bản thiết kế thi công cho `pipeline.py`.

---

## 0. Tổng quan luồng chạy

```text
                                  ┌──────────────── STAGE 0 (1 lần) ────────────────┐
                                  │  DataStore.load()   6 CSV → index trong RAM     │
                                  └──────────────────────┬──────────────────────────┘
                                                         │
   input/EC_xxx.json ──► STAGE 1 intake ──► STAGE 2 Coordinator plan
                                                         │
                       ┌─────────────────┬───────────────┼───────────────┐
                       ▼                 ▼               ▼               ▼
                 STAGE 3a          STAGE 3b        STAGE 3c        STAGE 3d
                 Customer        Order&Product      Payment         Delivery      (song song)
                       │                 │               │               │
                       └─────────────────┴───────┬───────┴───────────────┘
                                                 ▼
                                      STAGE 4  EvidenceBundle
                                                 ▼
                                      STAGE 5  Policy  (LLM ‖ rule engine)
                                                 ▼
                                      STAGE 6  Assemble CaseOutput
                                                 ▼
                                      STAGE 7  Verifier — 10 gate
                                          PASS ─┴─ FAIL ──► retry ≤2 về STAGE 2
                                                 ▼
                                      STAGE 8  Write output/ + trace.jsonl
```

Mỗi mũi tên giữa các agent là một `Handoff` và sinh đúng một dòng trong `logging/trace.jsonl`.

---

## STAGE 0 — DataStore

### 0.1 Chỉ nạp những gì output cần

Output schema không dùng đến `geolocation` (62 MB) và `order_reviews` (14 MB). Bỏ hai file này giảm **~76 MB / 60 %** khối lượng nạp và rút thời gian khởi động xuống dưới 5 giây.

| CSV | Nạp | Cột dùng |
|---|:---:|---|
| `olist_orders_dataset` | ✓ | tất cả 8 cột |
| `olist_order_items_dataset` | ✓ | tất cả 7 cột |
| `olist_order_payments_dataset` | ✓ | tất cả 5 cột |
| `olist_customers_dataset` | ✓ | `customer_id`, `customer_unique_id` |
| `olist_products_dataset` | ✓ | `product_id`, `product_category_name` |
| `olist_sellers_dataset` | ✓ | `seller_id` |
| `product_category_name_translation` | ✓ | chỉ khi bật profile category tiếng Anh |
| `olist_geolocation_dataset` | ✗ | không field nào của output cần |
| `olist_order_reviews_dataset` | ✗ | không field nào của output cần |

### 0.2 Index dựng sẵn

```python
class DataStore:
    orders:            dict[str, OrderRow]        # order_id  → order
    items_by_order:    dict[str, list[ItemRow]]   # sort theo order_item_id tăng dần
    payments_by_order: dict[str, list[PayRow]]    # sort theo payment_sequential tăng dần
    customers:         dict[str, str]             # customer_id → customer_unique_id
    orders_of_unique:  dict[str, list[str]]       # customer_unique_id → [order_id]
                                                  #   sort theo order_purchase_timestamp
    product_category:  dict[str, str | None]      # product_id → product_category_name
    seller_ids:        set[str]
```

Thứ tự sort là **hợp đồng**, không phải tiểu tiết: đề yêu cầu *"các array phải giữ thứ tự ổn định theo dữ liệu nguồn"*. Toàn bộ thứ tự phần tử trong output bắt nguồn từ ba dòng sort này.

### 0.3 Timestamp lưu song song hai dạng

```python
@dataclass(frozen=True)
class TS:
    raw: str | None      # "2018-03-31 15:23:33" — ghi thẳng ra output, không format lại
    dt:  datetime | None # dùng để tính toán
```

Ghi ra output luôn dùng `.raw`. Điều này loại bỏ mọi rủi ro lệch định dạng do `strftime` (mất số 0, thêm micro-second, đổi separator).

### 0.4 Quy ước số học

| Đại lượng | Quy tắc | Lý do |
|---|---|---|
| Mọi số tiền | Cộng bằng `Decimal`, xuất `float(round(dec, 2))` | Tổng các số 2 chữ số là **chính xác tuyệt đối** trong `Decimal`. Không dùng `float` trực tiếp vì sinh `212.26999999999998`. |
| Số giờ | `round(seconds / 3600, 2)` — hàm `round()` dựng sẵn | Chênh lệch **18 giây** = `0.005h`: `round()` cho `0.00`, làm tròn nửa-lên cho `0.01`. Bài chấm gần như chắc chắn viết bằng Python/pandas, cả hai đều dùng banker's rounding ⇒ bám theo `round()` là bắt chước chính xác bài chấm. |
| Dấu | Giữ nguyên, **được phép âm** | `delivery_variance_hours` âm nghĩa là giao sớm. |

```python
def hours_between(later: datetime, earlier: datetime) -> float:
    return round((later - earlier).total_seconds() / 3600, 2)
```

---

## STAGE 1 — Case intake

```python
@dataclass
class CaseInput:
    case_id: str                    # "EC_001"
    claimed_order_id: str
    language: str
    message: str
    include_customer_history: bool
    include_product_context: bool
    policy_version: str             # phải là "EC_POLICY_V2"
```

Kiểm tra vào:

1. `case_id` khớp `^EC_\d{3}$`.
2. `policy_version == "EC_POLICY_V2"` — khác thì log cảnh báo, vẫn xử lý theo V2.
3. `claimed_order_id` tồn tại trong `DataStore.orders`.

**Nếu `claimed_order_id` không tồn tại** — đề vẫn đòi đủ 50 file. Không được crash, không được bỏ file. Xử lý: sinh output với mọi array rỗng, mọi số `null`, `primary_issue = "unsupported_late_claim"`, `case_status = "no_action"`, `confidence = 0.50`, `evidence_ids = ["policy:DELIVERY_WITHIN_ESTIMATE"]`, và ghi cảnh báo `UNKNOWN_ORDER` vào trace. Thà mất điểm một case còn hơn hỏng cả lượt chạy.

---

## STAGE 2 — Coordinator: lập plan

Coordinator **không đọc CSV**. Nó chỉ thấy `CaseInput`.

```python
@dataclass
class DispatchPlan:
    agents: list[str]                  # ["customer", "order_product", "payment", "delivery"]
    questions: dict[str, str]          # agent → câu hỏi cụ thể cho case này
    rationale: str
```

LLM nhận `investigation_scope` và quyết định plan. Quyết định thật, không phải hình thức:

- `include_customer_history == False` → **bỏ Customer Agent**; `customer_context.related_order_ids = []`.
- `include_product_context == False` → Order & Product Agent vẫn chạy (cần cho item/seller) nhưng bỏ phần product/category.

**Fallback tất định:** LLM lỗi, timeout, hoặc trả JSON hỏng → dùng plan mặc định đủ 4 agent. Pipeline không bao giờ dừng vì LLM.

Ở lượt retry, Coordinator nhận thêm `failed_gates: list[GateFailure]` và chỉ dispatch lại agent liên quan tới gate hỏng.

---

## STAGE 3 — Bốn specialist agent (song song)

### 3.0 Hợp đồng chung

```python
@dataclass
class Fact:
    key: str            # "delivery_variance_hours"
    value: Any          # 87.39
    source_id: str      # "order:e481f51..."  ← BẮT BUỘC, dựng được từ CSV

@dataclass
class Handoff:
    case_id: str
    question: str
    from_agent: str
    to_agent: str
    facts: list[Fact]
    missing_or_conflicting: list[str]
    suggested_next: str
    ts: str
```

Trong mỗi agent, `facts` do **tool tất định** sinh ra; LLM chỉ viết `missing_or_conflicting` và `suggested_next`. LLM không được sửa `value` — nếu nó cố sửa, giá trị bị ghi đè bởi tool và ghi cảnh báo vào trace.

### 3a. Customer Agent

Scope: `customers`, `orders`(order_id, customer_id).

```python
customer_id        = orders[claimed].customer_id
customer_unique_id = customers[customer_id]
related            = [oid for oid in orders_of_unique[customer_unique_id]
                          if oid != claimed_order_id][:5]
```

| Fact | source_id |
|---|---|
| `customer_unique_id` | `order:<claimed>` |
| `related_order_ids` | `order:<claimed>` |
| `is_repeat_customer` | `order:<claimed>` |

`related_order_ids` **không bao giờ** vào `affected_entities` — đề nói rõ ở §3. Chúng chỉ sống trong `customer_context`.

### 3b. Order & Product Agent

Scope: `orders`, `order_items`, `products`, `sellers`, `category_translation`.

```python
items = items_by_order.get(claimed, [])          # đã sort theo order_item_id

item_ids      = [f"{claimed}:{it.order_item_id}" for it in items]
seller_ids    = unique_ordered(it.seller_id  for it in items)
product_ids   = unique_ordered(it.product_id for it in items)
categories    = unique_ordered(product_category[it.product_id] for it in items
                               if product_category.get(it.product_id))
```

`unique_ordered` = khử trùng lặp nhưng **giữ thứ tự xuất hiện đầu tiên**. Dùng cho cả 4 mảng để thoả điều kiện "thứ tự ổn định theo dữ liệu nguồn".

| Fact | source_id |
|---|---|
| `order_status` | `order:<claimed>` |
| `item_count`, `item_ids` | `item:<claimed>:<n>` mỗi item |
| `seller_ids` | `seller:<seller_id>` mỗi seller |
| `product_ids`, `category_names` | `item:<claimed>:<n>` |

Order không có item row → mọi mảng `[]`, và `missing_or_conflicting` ghi `"order has no item rows"`.

### 3c. Payment Agent

Scope: `order_payments`, `order_items`(price, freight_value).

```python
pays = payments_by_order.get(claimed, [])        # đã sort theo payment_sequential

payment_total = Σ Decimal(p.payment_value)
item_total    = Σ Decimal(it.price)
freight_total = Σ Decimal(it.freight_value)

if items:
    expected_total = item_total + freight_total
    difference     = payment_total - expected_total
    reconciled     = abs(difference) <= Decimal("0.10")
else:
    expected_total = difference = reconciled = None      # ← đề bắt buộc null

payment_types = unique_ordered(p.payment_type for p in pays)
payment_ids   = [f"{claimed}:{p.payment_sequential}" for p in pays]
```

Agent này **không thấy** `seller_id` hay `product_id`. Nó đối soát tiền, không kết luận trách nhiệm.

Lưu ý `payment_value` là số tiền của **từng payment row**, không phải từng installment (đề §2) — nên tổng là cộng thẳng, không nhân `payment_installments`.

### 3d. Delivery Agent

Scope: `orders`(timestamps), `order_items`(shipping_limit_date, seller_id).

```python
delivered   = order.order_delivered_customer_date
estimated   = order.order_estimated_delivery_date
carrier     = order.order_delivered_carrier_date

delivery_variance_hours = hours_between(delivered.dt, estimated.dt) if both else None

seller_handoff_analysis = []
for sid in unique_ordered(it.seller_id for it in items):
    limit = min(it.shipping_limit_date.dt for it in items if it.seller_id == sid)
    var   = hours_between(carrier.dt, limit) if carrier.dt else None
    seller_handoff_analysis.append({
        "seller_id": sid,
        "shipping_limit_at": raw_of(limit),
        "handoff_variance_hours": var,
        "late_handoff": (var is not None and var > 0),
    })

late_handoff_seller_ids = [s["seller_id"] for s in seller_handoff_analysis
                                          if s["late_handoff"]]
```

`min(...)` là phòng vệ, không phải cần thiết: probe toàn bộ `order_items` cho thấy **0 / 100.010** cặp `(order_id, seller_id)` có nhiều hơn một `shipping_limit_date`. Giữ `min()` để code vẫn đúng nếu dữ liệu chấm khác.

`carrier` null (1.783 order) → mọi `handoff_variance_hours = None`, `late_handoff = False`. Không suy đoán seller trễ khi không có dữ liệu bàn giao.

---

## STAGE 4 — EvidenceBundle

Coordinator gộp 4 handoff. Đây là **toàn bộ** những gì Policy Agent được thấy.

```python
@dataclass
class EvidenceBundle:
    case_id: str
    order_id: str
    order_status: str
    handoffs: list[Handoff]           # nguyên văn, để trace
    # các field phẳng do Coordinator trích ra từ facts:
    payment_total: Decimal | None
    payment_rows: int
    item_rows: int
    freight_total: Decimal | None
    expected_total: Decimal | None
    difference: Decimal | None
    reconciled: bool | None
    delivered_dt / estimated_dt / carrier_dt: datetime | None
    late_handoff_seller_ids: list[str]
    seller_ids / product_ids / category_names / item_ids / payment_ids: list[str]
    customer_unique_id: str | None
    related_order_ids: list[str]
```

---

## STAGE 5 — Policy Agent

### 5.1 Rule engine — nguồn chân lý

Khớp đầu tiên thì dừng.

```python
def decide(b: EvidenceBundle) -> PolicyDecision:
    paid = b.payment_total is not None and b.payment_total > 0
    late = (b.delivered_dt is not None
            and b.delivered_dt > b.estimated_dt)
    seller_late = len(b.late_handoff_seller_ids) > 0

    if b.order_status == "canceled"    and paid: → canceled_order_paid
    if b.order_status == "unavailable" and paid: → unavailable_order_paid
    if late and seller_late:                     → late_delivery_seller
    if late and not seller_late:                 → late_delivery_logistics
    if b.payment_rows >= 2 and b.reconciled:     → valid_split_payment
    otherwise:                                   → unsupported_late_claim
```

### 5.2 Bảng quyết định đầy đủ

| primary_issue | responsible_parties | refund | action chính | root cause |
|---|---|---|---|---|
| `canceled_order_paid` | `platform` / `OLIST_PLATFORM` | `payment_total` | `issue_full_refund` | `ORDER_CANCELED_AFTER_PAYMENT` |
| `unavailable_order_paid` | `platform` / `OLIST_PLATFORM` | `payment_total` | `issue_full_refund` | `ORDER_UNAVAILABLE_AFTER_PAYMENT` |
| `late_delivery_seller` | `seller` / mỗi seller trong `late_handoff_seller_ids` | `freight_total` | `refund_freight` | `SELLER_HANDOFF_AFTER_LIMIT` |
| `late_delivery_logistics` | `logistics_provider` / `LOGISTICS_PROVIDER` | `freight_total` | `refund_freight` | `CARRIER_DELIVERED_AFTER_ESTIMATE` |
| `valid_split_payment` | *(rỗng)* | `0` | `explain_valid_split_payment` | `MULTIPLE_PAYMENTS_RECONCILED` |
| `unsupported_late_claim` | *(rỗng)* | `0` | `reject_late_refund` | `DELIVERY_WITHIN_ESTIMATE` |

Sáu root-cause code của đề khớp **một-một** với sáu primary issue, và ví dụ §6 README chỉ có một phần tử trong `ranked_causes`. Kết luận: mỗi case đúng **một** cause, `rank: 1`.

### 5.3 Secondary issues — thứ tự cố định

Xét theo đúng thứ tự này, thoả thì thêm:

```python
1. multi_item_order      if item_rows >= 2
2. multi_seller_order    if len(seller_ids) >= 2
3. split_payment         if payment_rows >= 2
4. repeat_customer       if len(related_order_ids) >= 1
5. multiple_categories   if len(category_names) >= 2
```

### 5.4 Resolution actions — thứ tự cố định

```python
actions = [action_chinh]                                    # luôn đứng đầu
if seller_late:            actions += ["review_seller_handoff"]
elif late:                 actions += ["review_carrier_delay"]
if refund > 0:             actions += ["verify_refund_completion"]
if len(seller_ids) >= 2:   actions += ["coordinate_multi_seller_case"]
if payment_rows >= 2 and primary != "valid_split_payment":
                           actions += ["verify_payment_allocation"]
actions = actions[:5]
```

`review_seller_handoff` và `review_carrier_delay` loại trừ nhau — đề viết *"`review_seller_handoff` **hoặc** `review_carrier_delay`"*.

### 5.5 case_status

```python
case_status = "action_required" if refund > 0 else "no_action"
```

### 5.6 Nhánh LLM song song

LLM nhận `EvidenceBundle` (dạng text đã trình bày lại) và tự đề xuất `primary_issue` + lý do, **không thấy kết quả rule engine**.

```python
if llm_proposal == engine_result:
    agreement = True
else:
    agreement = False
    trace.warn("POLICY_DISCREPANCY", llm=llm_proposal, engine=engine_result)
# rule engine luôn thắng
```

### 5.7 confidence

```python
c = 1.00
c -= 0.15 if not agreement                        else 0
c -= 0.10 if delivered_dt is None                 else 0
c -= 0.05 if reconciled is False                  else 0
c -= 0.05 if item_rows == 0                       else 0
c -= 0.05 if any_array_truncated                  else 0
confidence = round(min(max(c, 0.50), 0.99), 2)
```

---

## STAGE 6 — Assemble CaseOutput

### 6.1 Giới hạn mảng

```python
LIMITS = {
    "order_ids": 5, "item_ids": 5, "seller_ids": 3, "payment_ids": 5,
    "related_order_ids": 5, "product_ids": 5, "category_names": 5,
    "ranked_causes": 3, "responsible_parties": 3,
    "evidence_ids": 20, "resolution_actions": 5,
}
```

Cắt luôn lấy **N phần tử đầu theo thứ tự nguồn** (đã sort ở Stage 0). Không sort lại, không lấy mẫu. Có cắt ⇒ bật cờ `any_array_truncated` ⇒ trừ confidence.

Dữ liệu thật có chạm giới hạn: 256 order > 5 item, 118 order > 5 payment, 5 order > 3 seller.

### 6.2 evidence_ids — thứ tự dựng và ưu tiên cắt

```python
evidence = ([f"order:{order_id}"]
          + [f"item:{order_id}:{n}"      for n in item_seq]      # theo order_item_id
          + [f"payment:{order_id}:{s}"   for s in pay_seq]       # theo payment_sequential
          + [f"seller:{sid}"             for sid in responsible_seller_ids]
          + [f"policy:{root_cause_code}"])
```

Trần 20 nhưng `policy:` **phải luôn có mặt**. Nếu tổng vượt 20, cắt phần `item:` trước, rồi `payment:`, và luôn chừa chỗ cho `order:` (1) và `policy:` (1).

Chỉ seller **chịu trách nhiệm** vào evidence, không phải mọi seller của order — đề §5: *"seller chịu trách nhiệm nếu có"*. Với `late_delivery_seller` đó là `late_handoff_seller_ids`; các nhánh khác không có seller nào.

### 6.3 Bảng ánh xạ field → nguồn

| Field output | Nguồn | Khi null / rỗng |
|---|---|---|
| `case_assessment.primary_issue` | Stage 5.1 | luôn có |
| `case_assessment.secondary_issues` | Stage 5.3 | `[]` |
| `case_assessment.case_status` | Stage 5.5 | luôn có |
| `case_assessment.confidence` | Stage 5.7 | luôn có |
| `affected_entities.order_ids` | `[claimed_order_id]` | luôn 1 phần tử |
| `affected_entities.item_ids` | Stage 3b | `[]` khi không item |
| `affected_entities.seller_ids` | Stage 3b — **mọi** seller của order | `[]` |
| `affected_entities.payment_ids` | Stage 3c | `[]` |
| `customer_context.customer_unique_id` | Stage 3a | `null` nếu thiếu |
| `customer_context.related_order_ids` | Stage 3a | `[]` khi scope tắt |
| `product_context.*` | Stage 3b | `[]` |
| `delivery_analysis.delivered_at` | `.raw` của timestamp | `null` |
| `delivery_analysis.delivery_variance_hours` | Stage 3d | `null` |
| `delivery_analysis.seller_handoff_analysis` | Stage 3d | `[]` |
| `payment_reconciliation.currency` | hằng `"BRL"` | luôn có |
| `payment_reconciliation.expected_total_brl` | Stage 3c | **`null`** khi không item |
| `payment_reconciliation.difference_brl` | Stage 3c | **`null`** khi không item |
| `payment_reconciliation.reconciled` | Stage 3c | **`null`** khi không item |
| `root_cause_analysis.ranked_causes` | Stage 5.2 | luôn 1 phần tử |
| `root_cause_analysis.responsible_parties` | Stage 5.2 | `[]` |
| `evidence_ids` | Stage 6.2 | luôn ≥1 |
| `financial_resolution.recommended_refund_brl` | Stage 5.2 | `0` chứ không phải null |
| `resolution_actions` | Stage 5.4 | luôn ≥1 |

`affected_entities.seller_ids` là **mọi** seller của order, khác với `evidence_ids` chỉ chứa seller chịu trách nhiệm. Hai chỗ này dùng danh sách khác nhau — nhầm lẫn ở đây làm hỏng cả hai nhóm điểm 15 %.

---

## STAGE 7 — Verifier: 10 gate

Chạy trước khi ghi bất kỳ file nào.

| # | Gate | Điều kiện fail | Sửa ở đâu |
|---|---|---|---|
| 1 | `SCHEMA` | Thiếu key bắt buộc hoặc sai kiểu | Stage 6 |
| 2 | `EVIDENCE_FORMAT` | ID không khớp 1 trong 5 regex | Stage 6.2 |
| 3 | `EVIDENCE_EXISTS` | order/item/payment/seller không có trong CSV | Stage 3 |
| 4 | `ARRAY_LIMIT` | Mảng vượt trần ở §6.1 | Stage 6.1 |
| 5 | `NULL_HANDLING` | `item_rows==0` mà 3 field kia khác `null` | Stage 3c |
| 6 | `ROUNDING` | Số tiền/giờ có quá 2 chữ số thập phân | Stage 0.4 |
| 7 | `TIMESTAMP` | Không khớp `^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$` và không `null` | Stage 0.3 |
| 8 | `STATUS_CONSISTENCY` | `refund>0` ⇎ `action_required` | Stage 5.5 |
| 9 | `ACTION_ORDER` | Action chính không đứng đầu, hoặc có `verify_payment_allocation` khi primary là `valid_split_payment` | Stage 5.4 |
| 10 | `SECONDARY_ORDER` | Sai thứ tự chuẩn 5 bước | Stage 5.3 |

Gate fail ⇒ **không ghi file**, trả `GateFailure(code, message, stage)` về Coordinator. Retry tối đa 2 lần, mỗi lần ghi trace. Hết retry mà vẫn fail: ghi file theo trạng thái tốt nhất hiện có, đánh dấu `VERIFIER_EXHAUSTED` trong trace — đề đòi đủ 50 file, file thiếu là hard gate.

Sau 10 gate, LLM Verifier (khác họ model với Policy Agent) đọc lại bundle + output soát nhất quán ngữ nghĩa. Cảnh báo được ghi trace nhưng **không tự sửa số**.

---

## STAGE 8 — Ghi artifact

### 8.1 output/

`output/EC_xxx.json`, tên khớp input, `json.dump(..., ensure_ascii=False, indent=2)`.

### 8.2 logging/trace.jsonl

Mở bằng mode `"w"` **một lần** ở đầu lượt chạy đủ 50 case — đề nói *"không append, chỉ cần lượt chạy mới nhất"*. Chạy lại một case đơn lẻ (`--case`) mở mode `"a"` để không xoá trace của 49 case kia.

Một dòng cho mỗi sự kiện:

```json
{"ts":"2026-08-05T13:42:01.123","case_id":"EC_001","event":"handoff",
 "from":"coordinator","to":"delivery","question":"...",
 "facts":[{"key":"delivery_variance_hours","value":87.39,"source_id":"order:e481f..."}],
 "missing_or_conflicting":[],"suggested_next":"..."}
```

| `event` | Sinh ra khi |
|---|---|
| `case_start` / `case_end` | Bắt đầu / kết thúc một case |
| `plan` | Coordinator lập plan |
| `handoff` | Mọi lượt chuyển giao giữa agent |
| `policy_decision` | Kèm cả `llm_proposal` và `engine_result` |
| `policy_discrepancy` | Hai nhánh lệch nhau |
| `gate_fail` | Verifier chặn |
| `retry` | Coordinator dispatch lại |
| `llm_call` | model, agent, token in/out, latency |

### 8.3 logging/metadata.json

```json
{
  "models": [
    {"agent": "coordinator", "model": "<tên model>", "parameter_size": "<số tham số>",
     "provider": "<provider>", "source_of_parameter_count": "<nguồn>"}
  ],
  "framework": "custom multi-agent orchestration (OpenAI-compatible client)",
  "runtime": {"python": "3.11.4", "os": "Windows 11", "pandas": "2.0.3"},
  "run": {"started_at": "...", "finished_at": "...", "cases": 50,
          "llm_calls": 0, "policy_discrepancies": 0, "gate_failures": 0}
}
```

Tên model khai báo **cứng trong `pipeline.py`**, không đặt trong `.env` — đề §9.4.

---

## 9. CLI

```bash
python run.py --all                  # 50 case, ghi mới trace.jsonl
python run.py --case EC_007          # chạy lại 1 case, append trace
python run.py --selftest             # chạy trên case sinh từ CSV, không cần input/
python run.py --all --workers 8      # fan-out song song giữa các case
python run.py --all --no-llm         # chỉ lõi tất định, bỏ mọi LLM call
```

`--no-llm` là van an toàn: nếu provider sập hoặc rate-limit giữa buổi thi, vẫn sinh đủ 50 output đúng schema từ rule engine. Mất phần điểm kiến trúc agent, giữ được phần lớn điểm nội dung.

Chạy lại một case là **idempotent** — ghi đè đúng file đó. Quy trình xử lý case lỗi: sửa agent/prompt/rule engine rồi chạy lại, **không sửa tay JSON**.

---

## 10. Self-test — chạy được ngay, không cần input

`--selftest` quét CSV, chọn `order_id` **có thật** phủ mọi nhánh và mọi edge case, dựng input đúng định dạng đề bài, chạy end-to-end.

| Nhánh / edge case | Order tồn tại | Order mẫu |
|---|---:|---|
| `canceled_order_paid` | 622 | `1b9ecfe83cdc259250e1a8aca174f0ad` |
| `unavailable_order_paid` | 609 | `8e24261a7e58791d10cb1bf9da94df5c` |
| `late_delivery_seller` | 2.128 | `203096f03d82e0dffbc41ebc2e2bcfb7` |
| `late_delivery_logistics` | 5.698 | `fbf9ac61453ac646ce8ad9783d7d0af6` |
| `valid_split_payment` | 2.693 | `e481f51cbdc54678b7cc49136f2d6af7` |
| `unsupported_late_claim` | 87.691 | `53cdb2fc8bc7dce0b6741e2150273451` |
| Không có item row | 775 | → gate 5 `NULL_HANDLING` |
| `delivered_customer_date` null | 2.965 | → `delivery_variance_hours = null` |
| > 5 item | 256 | → truncation |
| > 5 payment | 118 | → truncation |
| > 3 seller | 5 | → truncation |
| Không có payment row | 1 | → biên hiếm nhất |

Thêm ba unit test cố định lấy từ ví dụ §6 README — ground truth duy nhất có sẵn:

| Đại lượng | Tính lại | Đề ghi |
|---|---|---|
| `delivery_variance_hours` | `2018-03-31 15:23:33 − 2018-03-28 00:00:00` = 87,3925 | `87.39` ✓ |
| `handoff_variance_hours` | `21:33:51 − 20:31:15` = 1,043333 | `1.04` ✓ |
| refund `late_delivery_seller` | Σfreight = 18,27 | `18.27` ✓ |

Ba phép này khoá chặt quy ước đơn vị giờ thập phân + làm tròn 2 chữ số.

---

## 11. Thứ tự thi công

Bám đúng thứ tự này để **luôn có một hệ thống chạy được**, kể cả khi hết giờ:

| # | Hạng mục | Cần input? | Cần model? | Phần điểm ảnh hưởng |
|---|---|:---:|:---:|---|
| 1 | `DataStore` + `policy_engine` + Stage 6 assemble | ✗ | ✗ | ~90 % nội dung |
| 2 | Verifier 10 gate | ✗ | ✗ | chặn hard gate |
| 3 | `--selftest` | ✗ | ✗ | chứng minh 1–2 đúng |
| 4 | Agent + handoff + `trace.jsonl` | ✗ | ✓ | điểm kiến trúc |
| 5 | Gắn model vào `MODEL_REGISTRY` | ✗ | ✓ | ràng buộc đề |
| 6 | `metadata.json`, báo cáo cá nhân, `.gitignore` | ✗ | ✗ | deliverable bắt buộc |

Bước 1–3 làm được **ngay bây giờ**: không cần input, không cần model, không cần API key.
