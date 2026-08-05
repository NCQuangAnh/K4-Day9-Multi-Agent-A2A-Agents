# Báo cáo cá nhân — Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Lê Quang Trung |
| MSSV | 01158 |
| Khóa/Lớp | K4 |
| Vai trò chính | Phát triển pipeline evidence-first và deterministic verifier |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Trích xuất evidence và chuẩn hóa dữ liệu Olist | `run_pipeline.py`: `Store`, `Store.evidence` | Case JSON cùng các CSV orders, customers, items, payments, products | Evidence packet: order, item, payment, lịch sử khách hàng, product/category, phân tích giao hàng và đối soát thanh toán | Hoàn thành |
| Áp dụng chính sách và tạo output | `run_pipeline.py`: `policy`, `validate_output` | Evidence packet đã chuẩn hóa | 50 JSON trong `output/`, đúng schema và giới hạn mảng | Hoàn thành |
| Kiểm thử end-to-end | `test_pipeline.py` | `input/`, `output/`, `logging/trace.jsonl` | Kiểm tra 50 output canonical và 50 sự kiện validation thành công | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Thiết kế handoff và trace cho luồng multi-agent | `data_investigator`, `policy_resolver`, `deterministic_validator` | Mỗi case có các bước nhận case, tạo evidence, handoff, đối chiếu khuyến nghị và validation trong `logging/trace.jsonl`. |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Đối chiếu item + freight với payment và tính chênh lệch chính xác đến 2 chữ số | `Store.evidence` | Các trường `expected_total_brl`, `payment_total_brl`, `difference_brl`, `reconciled` | `python test_pipeline.py` |
| Xác định primary/secondary issues, bên chịu trách nhiệm, refund, action và evidence ID | `policy` | Output deterministic cho 50 case theo `EC_POLICY_V2` | `python test_pipeline.py` |
| Bảo vệ đầu ra khỏi kết quả model sai hoặc thiếu | `validate_output`, `evaluate_policy_handoff` | Chỉ ghi JSON bằng kết quả canonical đã kiểm tra | 50/50 case có `validation_completed: passed` trong trace |

Artifact đã kiểm chứng: `logging/run_summary.json` của lần chạy `run_20260805_170106` ghi nhận 50 case, 50 case đã validate. Phân bố primary issue là: 8 `canceled_order_paid`, 6 `unavailable_order_paid`, 10 `late_delivery_seller`, 10 `late_delivery_logistics`, 8 `valid_split_payment` và 8 `unsupported_late_claim`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Mỗi khiếu nại phải được kết luận từ dữ liệu có thể kiểm chứng, không từ nội dung khiếu nại hay suy diễn của model. Một order có thể có nhiều item, seller hoặc payment; vì vậy cần join đúng dữ liệu, tính đúng tiền/thời gian, rồi áp dụng thứ tự ưu tiên của `EC_POLICY_V2` để tạo output nhất quán.

### Cách triển khai

`Store` đọc CSV một lần và lập index theo `order_id`, `customer_id`, `product_id`; lịch sử khách được nhóm theo `customer_unique_id`. Với từng case, `Store.evidence` sắp xếp item/payment, tính tổng price, freight, payment bằng `Decimal`, và tính delivery/handoff variance từ timestamp CSV. Hàm `policy` áp dụng tuần tự các điều kiện: canceled/unavailable đã thanh toán, giao trễ do seller, giao trễ logistics, split payment hợp lệ, rồi mới đến claim không được hỗ trợ. Các issue phụ và actions được thêm theo thứ tự đề bài.

Hai agent model được tách vai trò audit evidence và đề xuất policy. Tuy nhiên kết quả cuối không để model ghi đè dữ liệu: `policy` tạo kết quả canonical và `validate_output` so sánh toàn bộ output với kết quả đó trước khi ghi file. Trace ghi rõ evidence packet, handoff và trạng thái validation của từng case.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | 50 `input/EC_*.json` và các CSV Olist trong `data/` |
| Output | 50 `output/EC_*.json`, mỗi file tuân theo schema đề bài |
| Module phụ thuộc | `run_pipeline.py`, thư mục `data/`, `input/` |
| Module sử dụng output | `test_pipeline.py`, `output.zip`, người chấm |
| Điều kiện lỗi cần xử lý | Order không tồn tại; output lệch canonical; evidence ID không hợp lệ; vượt giới hạn mảng; confidence ngoài `[0,1]`; thiếu event validation trong trace |

### Cách xác minh

```bash
python test_pipeline.py
```

- **Kết quả mong đợi:** Có đúng 50 input, 50 output và tất cả output khớp kết quả policy canonical; mỗi case có event validation thành công.
- **Kết quả thực tế:** `PASS: 50 inputs -> 50 outputs; 50 cases validated in trace.`
- **Artifact/log:** `output/`, `logging/trace.jsonl`, `logging/run_summary.json`.

Lần xác minh này dùng artifact của dry-run; do đó nó xác thực dữ liệu, policy, schema và trace, nhưng không khẳng định đã gọi thành công API model.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Model có thể diễn giải sai policy hoặc tạo evidence không tồn tại, trong khi output bị chấm theo dữ liệu và schema chặt chẽ.
- **Các phương án đã cân nhắc:** (1) để policy agent tự sinh JSON cuối; (2) dùng model chỉ để audit/đề xuất, còn policy và output được tính deterministically.
- **Phương án đã chọn:** Phương án (2).
- **Lý do:** Quy tắc `EC_POLICY_V2` và các phép tính tài chính có thể biểu diễn chính xác bằng code; cách này giúp reproducible, tránh hallucination, và vẫn giữ handoff multi-agent trong trace.
- **Bằng chứng quyết định phù hợp:** `test_pipeline.py` đối chiếu từng output với `policy(Store().evidence(case))`; toàn bộ 50 case pass.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Với `late_delivery_seller` có nhiều seller giao trễ, implementation ban đầu có nguy cơ chỉ gán seller đầu tiên là bên chịu trách nhiệm.
- **Lệnh hoặc bước tái hiện:** Chạy policy cho order có nhiều seller và kiểm tra `delivery_analysis.late_handoff_seller_ids` so với `root_cause_analysis.responsible_parties`.
- **Nguyên nhân gốc:** Nhánh policy dùng một tuple `party` đơn lẻ, trong khi contract yêu cầu liệt kê các seller vi phạm, tối đa 3.
- **Cách xử lý:** Khi primary issue là `late_delivery_seller`, tạo `responsible_parties` từ toàn bộ `late_sellers[:3]` và thêm evidence ID seller tương ứng.
- **Cách xác minh sau khi sửa:** `test_pipeline.py` kiểm tra danh sách party ID phải trùng `late_handoff_seller_ids`; toàn bộ 50 case pass.
- **Điều học được:** Cần biểu diễn rõ cardinality của entity trong contract; một biến scalar dễ làm mất dữ liệu khi chuyển sang trường list.

## 7. Hiểu biết về luồng end-to-end

Mẫu báo cáo gốc có các câu hỏi về Crossref/vector index, evaluation set và freshness monitoring; các thành phần này không thuộc bài Olist Multi-Agent A2A hiện tại. Luồng end-to-end của bài này là:

1. Pipeline đọc `claimed_order_id` từ case JSON, lấy order và join customer, item, payment, product từ CSV. Các khóa chính là `order_id`, `customer_id` và `product_id`.
2. Evidence packet chứa facts đã chuẩn hóa: lịch sử khách, sản phẩm, payment reconciliation, delivery variance và seller handoff variance. Đây là handoff cho data investigator và policy resolver.
3. Policy resolver có thể đưa đề xuất, nhưng deterministic validator luôn tính output canonical theo `EC_POLICY_V2`, kiểm tra schema/limit/evidence ID rồi mới ghi JSON.
4. Cùng một tập 50 case được dùng cho mọi lần chạy và cho `test_pipeline.py`, nên có thể so sánh kết quả trước/sau sửa mà không bị thay đổi dữ liệu đầu vào.
5. Repair chỉ được xem là thành công khi output khớp policy canonical và trace có một event `validation_completed` với `status: passed` cho từng case. Lần chạy hiện tại đạt 50/50.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng; phần API model được nêu rõ là dry-run.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Lê Quang Trung  
**Ngày xác nhận:** 2026-08-05
