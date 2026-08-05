# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Lê Tuấn Minh |
| MSSV            | 2A202601390 |
| Khóa/Lớp        | K4 |
| Vai trò chính   | Kiểm chứng, chất lượng đầu ra & công cụ đo |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Verifier 10 gate | `core.py` — `Verifier.run` và 10 hàm `_gate_*` | `CaseOutput` đã dựng | Danh sách `GateFailure`, chặn trước khi ghi file | Hoàn thành |
| Kiểm tra schema theo từng file | `check_schema.py` | Thư mục `output/` | Báo cáo 9 nhóm kiểm tra cho từng file trong 50 file | Hoàn thành |
| Bộ self-test và unit test | `run.py` — `cmd_selftest`, `build_selftest_cases`, `cmd_unittest` | `DataStore` | 12 case sinh từ CSV thật + 5 phép tính từ ví dụ README | Hoàn thành |
| Đóng gói và kiểm tra bài nộp | `run.py` — `cmd_validate`, `cmd_zip` | `output/` | `output.zip` 50 file, phẳng, không file lạ | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Kiểm toán độc lập bằng pandas thuần | Toàn bộ pipeline | Viết lại logic không dùng `core.py`, đối chiếu 50 case × 19 field, 0 sai lệch |
| Bắt lỗi vi phạm schema | Module Assembler | Xác định `item_total_brl`/`freight_total_brl` không được phép `null` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| 10 gate chặn output sai trước khi ghi file | `core.Verifier` | 0 file fail trên lượt chạy chính thức | `python run.py --validate` |
| Trình kiểm tra schema theo từng file | `check_schema.py` | 50/50 PASS, 9 nhóm kiểm tra | `python check_schema.py output` |
| Thử nghiệm âm chứng minh trình kiểm tra hoạt động | 8 file lỗi cố ý | Bắt đúng 8/8, mỗi lỗi vào đúng nhóm | Tạo file lỗi rồi chạy lại `check_schema.py` |
| Kiểm toán độc lập | Script pandas thuần | 50 case × 19 field, 0 sai lệch | So từng field với bản cài đặt độc lập |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Thử nghiệm âm của `check_schema.py`: tạo 8 file lỗi có chủ đích — BOM UTF-8 kèm `delivered_at = "N/A"`, `confidence = 1.5`, `item_ids` 9 phần tử vượt trần 5, thiếu key `evidence_ids`, `secondary_issues` sai thứ tự, số `12.3456` quá 2 chữ số, `currency = "USD"`, và một key thừa. Trình kiểm tra bắt đúng cả 8, mỗi lỗi rơi vào đúng nhóm (`encode`, `enum`, `limits`, `keys`, `order`, `round`). Một trình kiểm tra luôn báo PASS thì vô giá trị, nên phép thử này là bắt buộc.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Verifier chỉ kiểm tra được tính nhất quán nội tại — nó không phát hiện được nếu toàn bộ logic sai theo cùng một cách. Cần một lớp kiểm chứng độc lập thật sự, và cần chứng minh chính các công cụ kiểm tra là đáng tin.

### Cách triển khai

Ba lớp độc lập nhau. Lớp một là 10 gate trong `core.Verifier`, chạy trước khi ghi bất kỳ file nào, trong đó gate 3 tra ngược từng evidence ID về `DataStore` nên ID bịa không thể lọt. Lớp hai là `check_schema.py`, so khớp cấu trúc với ví dụ schema ở README §6 qua 9 nhóm: encode, keys, types, limits, enum, order, nested, timestamp, round — và báo cáo riêng cho từng file. Lớp ba là bản kiểm toán viết bằng pandas thuần, cố tình **không** dùng lại `core.py`: nếu hai bản cài đặt độc lập cho cùng kết quả thì khả năng cả hai cùng sai theo cùng một kiểu là rất thấp.

### Input, output và contract

| Thành phần              | Mô tả |
| ----------------------- | ----- |
| Input                   | `output/EC_xxx.json` đã dựng, cùng `DataStore` để tra ngược evidence ID |
| Output                  | Danh sách `GateFailure(code, message, stage)`; `stage` chỉ thẳng nơi cần sửa |
| Module phụ thuộc        | `core.DataStore`, `core.LIMITS`, `core.PRIMARY_ACTION_OF`, `core.SECONDARY_ORDER` |
| Module sử dụng output   | `pipeline.VerifierAgent` (chặn trước khi ghi), `run.py --validate` (kiểm tra lại `output/`) |
| Điều kiện lỗi cần xử lý | Gate fail → không ghi file, trả lý do về Coordinator để chạy lại có mục tiêu; hết 2 lần retry vẫn fail → ghi file theo trạng thái tốt nhất và đánh dấu `VERIFIER_EXHAUSTED`, vì thiếu file là hard gate |

### Cách xác minh

```bash
python run.py --validate
python check_schema.py output
python run.py --zip
```

- **Kết quả mong đợi:** 0 gate fail, 50/50 PASS schema, zip đúng 50 file không file lạ
- **Kết quả thực tế:** Đúng như mong đợi trên lượt chạy chính thức. `output.zip` 50 file phẳng, không BOM, không chuỗi `N/A`, khớp 0/50 khác với `output/`.
- **Artifact/log:** Log của `--validate` và `check_schema.py`; `output.zip`

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần quyết định làm gì khi một case không qua nổi 10 gate sau khi đã retry hết.
- **Các phương án đã cân nhắc:** (a) Bỏ qua case đó, không ghi file. (b) Vẫn ghi file theo trạng thái tốt nhất hiện có và đánh dấu trong trace.
- **Phương án đã chọn:** Phương án (b).
- **Lý do:** Đề yêu cầu đúng 50 file; thiếu file là hard gate làm hỏng cả bài nộp. Mất điểm một case vẫn tốt hơn hỏng toàn bộ lượt chạy.
- **Bằng chứng quyết định phù hợp:** Nguyên tắc này cũng được áp cho trường hợp `claimed_order_id` không tồn tại trong CSV: sinh output rỗng nhưng hợp lệ, ghi cảnh báo `UNKNOWN_ORDER` vào trace thay vì để pipeline dừng.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Một lần nộp bị bài chấm cho 0 điểm toàn bài, dù `check_schema.py` báo 50/50 PASS.
- **Lệnh hoặc bước tái hiện:** Sinh output với `item_total_brl` và `freight_total_brl` đặt `null` cho 6 order không có item row, rồi nộp.
- **Nguyên nhân gốc:** README §4 chỉ cho phép `null` ở đúng ba field: `expected_total_brl`, `difference_brl`, `reconciled`. Ví dụ §6 cho thấy `item_total_brl` và `freight_total_brl` luôn là số. Lỗi nằm ở chính `check_schema.py`: nó đánh dấu hai field đó là 'cho phép null' nên báo PASS cho một output vi phạm schema.
- **Cách xử lý:** Siết `check_schema.py`: `item_total_brl`, `freight_total_brl`, `payment_total_brl` chuyển sang không cho phép `null`. Sau đó chạy lại chính trình kiểm tra đã siết trên bản gây lỗi.
- **Cách xác minh sau khi sửa:** Chạy `python check_schema.py variants/money_null` → bắt đúng 6 file với 12 lỗi `null (khong duoc phep)`. Chạy trên `output/` mới → 50/50 PASS.
- **Điều học được:** Một trình kiểm tra sai còn nguy hiểm hơn không có trình kiểm tra, vì nó tạo cảm giác an toàn giả. Sau mỗi lần siết quy tắc, phải chạy lại trên chính dữ liệu từng gây lỗi để chứng minh nó bắt được.

## 7. Hiểu biết về luồng end-to-end

Nội dung mục này trả lời 5 câu hỏi end-to-end của bài lab RAG.

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. Pipeline lấy bản ghi học thuật từ Crossref qua API, chuẩn hóa các trường cần tìm kiếm như tiêu đề, abstract, tác giả, năm xuất bản, DOI và URL. Mỗi bản ghi được gán document ID ổn định, làm sạch/chia nhỏ nội dung khi cần, rồi đưa qua embedding model để biến thành vector. Vector được lưu vào vector index cùng metadata và document ID. Khi có câu hỏi, hệ thống embedding câu hỏi, tìm các vector gần nhất và dùng các document được truy hồi làm ngữ cảnh để tạo câu trả lời.

2. Evaluation set là tập câu hỏi chuẩn để chạy đánh giá lặp lại được. Với mỗi câu hỏi, ground-truth document IDs chỉ ra các tài liệu đáng lẽ phải được truy hồi. Retrieval quality được đo bằng việc các ID đúng có xuất hiện trong top-*k* hay không, ví dụ Recall@k hoặc Hit@k. Answer quality được đánh giá dựa trên việc câu trả lời có đúng, bám vào các tài liệu ground truth và có dẫn chứng phù hợp hay không; retrieval tốt là điều kiện quan trọng nhưng không tự động bảo đảm câu trả lời tốt.

3. Quality checks kiểm tra chất lượng và tính hợp lệ của dữ liệu/index tại một thời điểm: schema và trường bắt buộc, DOI/document ID, bản ghi trùng, nội dung rỗng, embedding thiếu hoặc metadata không khớp. Freshness monitoring theo dõi dữ liệu có còn mới và pipeline có cập nhật đúng lịch hay không, chẳng hạn thời điểm đồng bộ Crossref gần nhất, độ trễ ingest và số bản ghi mới. Nói ngắn gọn, quality trả lời “dữ liệu có đúng và dùng được không?”, còn freshness trả lời “dữ liệu có đủ mới không?”.

4. Dùng cùng một test set giúp phép so sánh công bằng: khác biệt metric chỉ đến từ trạng thái hệ thống (baseline, dữ liệu/index bị corrupt, hay bản đã repair), không phải do câu hỏi dễ hoặc khó khác nhau. Nhờ vậy có thể xác định mức suy giảm do corruption và kiểm chứng repair có thực sự khôi phục chất lượng thay vì chỉ tình cờ đạt điểm tốt trên một tập khác.

5. Repair thành công khi artifact sau sửa cho thấy pipeline đã được khôi phục — ví dụ index được rebuild/cập nhật, báo cáo kiểm tra chất lượng không còn lỗi liên quan và log chạy evaluation hoàn tất. Về metric, retrieval trên cùng evaluation set phải phục hồi về mức baseline hoặc đạt ngưỡng chấp nhận đã đặt ra (như Recall@k/Hit@k); answer-quality score cũng phải đạt ngưỡng tương ứng và không còn lỗi do document ID, metadata hay context bị hỏng. Cần xem đồng thời artifact và metric, vì chỉ có index mới mà metric không phục hồi thì repair chưa được chứng minh là thành công.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Lê Tuấn Minh
**Ngày xác nhận:** 2026-08-05
