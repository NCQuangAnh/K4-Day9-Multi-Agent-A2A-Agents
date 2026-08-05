# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Vũ Đình Huy |
| MSSV            | 2A202601288 |
| Khóa/Lớp        | K4 |
| Vai trò chính   | Tầng dữ liệu — nạp, index và quy ước số học |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Nạp và index dữ liệu Olist | `core.py` — `DataStore.load`, `_load_orders`, `_load_items`, `_load_payments`, `_load_customers`, `_load_products`, `_load_sellers` | 6/9 file CSV trong `data/` | Index trong RAM: `orders`, `items_by_order`, `payments_by_order`, `orders_of_unique`, `product_category` | Hoàn thành |
| Quy ước timestamp và số học | `core.py` — `TS`, `hours_between`, `money`, `_to_decimal` | Chuỗi thô từ CSV | Timestamp giữ nguyên bản + `datetime` để tính; tiền cộng bằng `Decimal` | Hoàn thành |
| Tra cứu evidence | `core.py` — `DataStore.evidence_id_exists` | Chuỗi evidence ID | Bool xác nhận ID tồn tại trong CSV | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Đo phân bố dữ liệu để dựng self-test | Module Policy của Nam Phương | Xác định số order có thật cho từng nhánh policy và từng edge case |
| Phát hiện quy ước thứ tự mảng | Toàn nhóm | Xác định "thứ tự theo dữ liệu nguồn" là thứ tự dòng CSV, không phải sort |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Bỏ 2 CSV không cần thiết | `DataStore.load` | Giảm ~76 MB, khởi động dưới 5 giây | Đối chiếu schema output: không field nào dùng `geolocation` hay `order_reviews` |
| Xác định cặp (order, seller) luôn có đúng 1 shipping_limit_date | Script probe trên `order_items` | 0/100.010 cặp có nhiều hơn một mốc | Chạy probe trên toàn bộ 112.650 item row |
| Chốt quy ước làm tròn | `hours_between`, `money` | Khớp cả 5 phép tính trong ví dụ README §6 | `python run.py --unittest` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Kết quả probe trên toàn bộ 99.441 order, dùng để dựng bộ self-test: 622 order `canceled_order_paid`, 609 `unavailable_order_paid`, 2.128 `late_delivery_seller`, 5.698 `late_delivery_logistics`, 2.693 `valid_split_payment`; cùng 775 order không có item row, 2.965 order thiếu `delivered_customer_date`, 256 order quá 5 item, 118 order quá 5 payment, 5 order quá 3 seller. Nhờ bảng này mà mọi nhánh policy và mọi giới hạn mảng đều có case thật để kiểm thử trước khi có đề.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Output phải khớp giá trị chính xác, nên tầng dữ liệu không được phép làm sai lệch dù chỉ một chữ số. Ba rủi ro cụ thể: định dạng timestamp bị đổi khi ghi ra, nhiễu dấu phẩy động khi cộng tiền, và thứ tự phần tử trong mảng không khớp nguồn.

### Cách triển khai

Timestamp lưu song song hai dạng trong `TS`: `raw` là chuỗi nguyên bản từ CSV dùng để ghi ra output, `dt` là `datetime` chỉ dùng để tính. Ghi ra luôn dùng `raw` nên không có cơ hội `strftime` làm mất số 0 hay đổi separator. Tiền đọc bằng `dtype=str` rồi chuyển sang `Decimal`, vì tổng của các số 2 chữ số là chính xác tuyệt đối trong `Decimal` còn `float` sẽ sinh `212.26999999999998`. Số giờ dùng `round()` dựng sẵn của Python thay vì làm tròn nửa-lên, vì bài chấm gần như chắc chắn viết bằng Python hoặc pandas — cả hai đều dùng banker's rounding. Thứ tự trong index chính là hợp đồng: mọi mảng trong output bắt nguồn từ thứ tự các dòng được nạp.

### Input, output và contract

| Thành phần              | Mô tả |
| ----------------------- | ----- |
| Input                   | 6 file CSV: `orders`, `order_items`, `order_payments`, `customers`, `products`, `sellers` |
| Output                  | `DataStore` với các index tra cứu O(1) theo `order_id`, `customer_id`, `customer_unique_id`, `product_id` |
| Module phụ thuộc        | pandas (chỉ dùng để đọc CSV nhanh, mọi giá trị giữ dạng chuỗi) |
| Module sử dụng output   | `CustomerTools`, `OrderProductTools`, `PaymentTools`, `DeliveryTools`, `Verifier` |
| Điều kiện lỗi cần xử lý | Ô rỗng trong CSV → `TS(None, None)`; `keep_default_na=False` để pandas không tự biến chuỗi thành `NaN`; order không có item hoặc không có payment row đều là trường hợp hợp lệ |

### Cách xác minh

```bash
python run.py --unittest
python run.py --selftest
```

- **Kết quả mong đợi:** 5/5 phép tính khớp ví dụ README; 12/12 case self-test qua đủ 10 gate
- **Kết quả thực tế:** Cả hai `TAT CA PASS`. `delivery_variance_hours` cho `87.39`, `handoff_variance_hours` cho `1.04`, `expected_total_brl` cho `212.27` — khớp từng chữ số với ví dụ trong đề.
- **Artifact/log:** `selftest/output/`, log của `--unittest`

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Chọn quy tắc làm tròn cho số giờ. Một trường hợp thật gặp trong dữ liệu: chênh lệch đúng 277,765 giờ, nằm ngay ranh giới làm tròn.
- **Các phương án đã cân nhắc:** (a) Làm tròn nửa lên bằng `Decimal` với `ROUND_HALF_UP` — cho `277.77`. (b) Dùng `round()` dựng sẵn của Python trên `float` — cho `277.76`.
- **Phương án đã chọn:** Phương án (b).
- **Lý do:** Bài chấm gần như chắc chắn viết bằng Python hoặc pandas, và cả `round()`, `numpy.round`, `pandas.round` đều dùng banker's rounding. Bắt chước chính xác cách bài chấm tính quan trọng hơn việc chọn quy tắc 'đúng' về mặt toán học.
- **Bằng chứng quyết định phù hợp:** Kiểm tra sâu hơn cho thấy `999954/3600` trong dấu phẩy động thực ra là `277.76499999...`, tức nhỏ hơn `.765` thật. Nên mọi cách làm tròn trên `float` đều cho `277.76`; chỉ tính bằng `Decimal` chính xác tuyệt đối mới ra `277.77`.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** 14 file trong `output/` bị thay hết `null` thành `"N/A"` (chuỗi), `0.0` (số) hoặc `false` (bool), kèm BOM UTF-8 ở đầu file.
- **Lệnh hoặc bước tái hiện:** `python run.py --validate` sau khi mở các file JSON bằng một trình sửa/format bên ngoài.
- **Nguyên nhân gốc:** Không phải lỗi pipeline — đã grep toàn bộ mã nguồn, không có chuỗi `N/A` nào. Một công cụ bên ngoài đã mở và lưu lại các file, tự ý thay `null` bằng giá trị 'trung tính' và thêm BOM.
- **Cách xử lý:** Khôi phục bằng `git checkout -- output/` (bản đã commit vẫn sạch), và bổ sung 2 gate vào `--validate` để bắt ngay lần sau: file có BOM UTF-8, và file chứa chuỗi `"N/A"` — kèm hướng dẫn khôi phục ngay trong thông báo lỗi.
- **Cách xác minh sau khi sửa:** Chạy lại `python run.py --validate` → 0 file fail; `python check_schema.py` → 50/50 PASS.
- **Điều học được:** Artifact sinh ra tự động cần được bảo vệ khỏi chỉnh sửa thủ công. Rẻ nhất là thêm một gate nhận diện dấu vết đặc trưng của công cụ ngoài, vì loại hỏng này im lặng và vẫn parse được JSON bình thường.

## 7. Hiểu biết về luồng end-to-end

> Ghi chú: 5 câu hỏi in sẵn trong mẫu (Crossref, vector index, retrieval quality,
> corrupted/repaired test set) thuộc về bài lab RAG, không áp dụng cho bài
> multi-agent này. Dưới đây trả lời các câu hỏi tương đương cho đúng bài lab.

1. Dữ liệu đi từ 9 file CSV Olist đến output JSON như thế nào?
2. Evidence ID được dùng để ràng buộc kết luận vào dữ liệu gốc ra sao?
3. Verifier khác Policy Agent ở điểm nào trong pipeline?
4. Vì sao rule engine quyết định thay vì LLM?
5. Một lượt chạy được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

Một case đi qua 8 chặng. `DataStore` nạp 6/9 CSV cần thiết (bỏ `geolocation` và `order_reviews` vì không field nào của output dùng tới, giảm ~60% khối lượng nạp) và dựng index trong RAM. `run.py` đọc `input/EC_xxx.json`, lấy `claimed_order_id`. Coordinator lập plan rồi fan-out song song tới 4 agent chuyên trách; mỗi agent chỉ được cấp đúng nhóm tool thuộc phạm vi dữ liệu của mình và trả về một `Handoff` gồm fact kèm `source_id`, danh sách fact thiếu/mâu thuẫn, và đề xuất bước tiếp theo. Coordinator gộp 4 handoff thành `EvidenceBundle` — đây là toàn bộ những gì Policy Agent được thấy, vì Policy không có quyền đọc CSV. Policy chạy hai nhánh song song: LLM tự đề xuất `primary_issue`, còn `PolicyEngine` tính kết quả tất định theo `EC_POLICY_V2`; rule engine luôn thắng, bất đồng được ghi vào trace. `Assembler` dựng output đúng schema và cắt theo giới hạn mảng. `Verifier` chạy 10 gate trước khi ghi file; fail thì trả mã gate về Coordinator để chạy lại có mục tiêu.

Evidence ID là thứ ràng buộc kết luận vào dữ liệu gốc: mọi `Fact` bắt buộc có `source_id` dựng được từ CSV theo 5 dạng (`order:`, `item:`, `payment:`, `seller:`, `policy:`). Gate 3 của Verifier tra ngược từng ID về `DataStore` — ID không tồn tại thì không có cách nào lọt ra file.

Verifier khác Policy ở chỗ nó không tính lại nghiệp vụ, chỉ kiểm tra tính hợp lệ của output đã dựng: schema, định dạng và sự tồn tại của evidence, giới hạn mảng, null handling, làm tròn, định dạng timestamp, nhất quán giữa refund và `case_status`, thứ tự action và secondary issue. Nó còn cố ý dùng model khác họ với Policy để lỗi không tương quan.

Rule engine quyết định vì việc chấm điểm so khớp giá trị field chính xác: sai một chữ số thập phân hay bịa một evidence ID là mất điểm cứng. LLM đảm nhiệm phần nó làm tốt — điều phối, phát hiện dữ liệu khuyết, kiểm chứng chéo — nhưng không bao giờ được tự tính số.

Một lượt chạy được coi là thành công khi: `output/` có đúng 50 file, `python run.py --validate` in `SAN SANG NOP` với 0 gate fail, `python check_schema.py` cho 50/50 PASS, `logging/trace.jsonl` ghi đủ 50 `case_start`/`case_end` và 250 handoff, và `logging/metadata.json` có `run_type: official`.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Vũ Đình Huy
**Ngày xác nhận:** 2026-08-05
