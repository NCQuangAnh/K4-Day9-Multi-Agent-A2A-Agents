# Multi-Agent E-commerce Dispute Resolution - Architecture

## System Overview

Hệ thống multi-agent xử lý khiếu nại thương mại điện tử trên dữ liệu Olist. Sử dụng 7 agents chuyên biệt với phân công rõ ràng, handoff kết quả giữa các agent, và kiểm chứng đầu ra cuối cùng.

**Model**: `llama-3.1-8b-instant` (8B parameters) via Groq API

## Agent Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    INPUT LAYER                          │
│              EC_001.json ... EC_050.json                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│               COORDINATOR AGENT                         │
│  Vai trò: Nhận case, điều phối, tổng hợp output        │
│  Quyền: Đọc input JSON, gọi tất cả sub-agents          │
│  LLM: Đánh giá confidence score                         │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
│ CUSTOMER │ │ ORDER &  │ │ PAYMENT │ │ DELIVERY │
│ AGENT    │ │ PRODUCT  │ │ AGENT   │ │ AGENT    │
│          │ │ AGENT    │ │         │ │          │
│ Vai trò: │ │ Vai trò: │ │ Vai trò:│ │ Vai trò: │
│ Identity │ │ Items,   │ │ Đối    │ │ Variance │
│ & History│ │ Products,│ │ soát   │ │ & Handoff│
│          │ │ Sellers  │ │ payment│ │ Analysis │
│ Quyền:   │ │ Quyền:   │ │ Quyền: │ │ Quyền:   │
│ customers│ │ items,   │ │ payment│ │ orders,  │
│ orders   │ │ products,│ │ items  │ │ items    │
│          │ │ sellers  │ │        │ │          │
└──────┬───┘ └──────┬───┘ └────┬───┘ └──────┬───┘
       │            │          │             │
       └────────────┴──────────┴─────────────┘
                         │
                         ▼ (handoff results)
              ┌─────────────────────┐
              │    POLICY AGENT     │
              │ Vai trò: Áp dụng    │
              │ EC_POLICY_V2        │
              │ Quyền: Nhận kết quả │
              │ từ 4 agents trên    │
              └──────────┬──────────┘
                         │
                         ▼ (handoff assessment)
              ┌─────────────────────┐
              │   VERIFIER AGENT    │
              │ Vai trò: Validate   │
              │ schema, evidence,   │
              │ array limits        │
              │ Quyền: Đọc CSV      │
              │ để verify evidence  │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │    OUTPUT LAYER     │
              │ EC_xxx.json output  │
              │ + trace.jsonl       │
              └─────────────────────┘
```

## Agent Details

| Agent | Vai trò | Quyền truy cập dữ liệu | Input | Output |
|-------|---------|------------------------|-------|--------|
| **CoordinatorAgent** | Nhận case, điều phối agents, tổng hợp output | Input JSON, gọi sub-agents | Case JSON | Final output JSON |
| **CustomerAgent** | Xác định customer và lịch sử | `customers`, `orders` | `order_id` | `customer_context` |
| **OrderProductAgent** | Phân tích items, products, sellers | `order_items`, `products`, `sellers` | `order_id` | `affected_entities`, `product_context` |
| **PaymentAgent** | Đối soát payment với item+freight | `order_payments` + items data | `order_id`, `items_raw` | `payment_reconciliation` |
| **DeliveryAgent** | Tính delivery variance, handoff | `orders` + items data | `order_id`, `items_raw` | `delivery_analysis` |
| **PolicyAgent** | Áp dụng EC_POLICY_V2 | Kết quả từ 4 agents | All agent results | Assessment, root cause, refund, actions |
| **VerifierAgent** | Validate schema, evidence | CSV data (verify IDs) | Draft output | Corrected output |

## Handoff Flow

1. **Coordinator** nhận input case → extract `order_id`
2. **Coordinator** dispatch song song tới 4 agents:
   - CustomerAgent → `customer_context`
   - OrderProductAgent → `affected_entities` + `product_context` + `items_raw`
   - PaymentAgent (nhận `items_raw` từ OrderProduct) → `payment_reconciliation`
   - DeliveryAgent (nhận `items_raw` từ OrderProduct) → `delivery_analysis`
3. **PolicyAgent** nhận kết quả từ 4 agents → áp dụng rules → `case_assessment` + `root_cause` + `refund` + `actions`
4. **Coordinator** merge results, gọi LLM cho `confidence`
5. **VerifierAgent** validate output cuối → evidence IDs, array limits, null handling
6. Output JSON được ghi ra file

## Design Principles

- **Deterministic calculations**: Delivery variance, payment reconciliation, policy rules đều tính bằng Python thuần
- **LLM for reasoning**: Chỉ dùng LLM cho confidence scoring (CoordinatorAgent)
- **Data isolation**: Mỗi agent chỉ truy cập data tables cần thiết
- **Traceability**: Mọi action và LLM call đều được log vào `trace.jsonl`
