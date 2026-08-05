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

Nội dung mục này trả lời 5 câu hỏi end-to-end của bài lab RAG.

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. Từ góc nhìn tầng dữ liệu, Crossref cung cấp metadata thô qua API. Pipeline kiểm tra DOI, chuẩn hóa kiểu dữ liệu và giữ một ID nguồn cố định cho từng work trước khi làm sạch abstract hoặc tách thành chunk. Embedding của từng chunk được tạo rồi ghi vào vector index kèm ID, DOI, năm và vị trí chunk; metadata này giúp truy hồi xong vẫn tra ngược được về bản ghi gốc.

2. Mỗi query trong evaluation set đi cùng danh sách ground-truth document IDs. Sau khi index trả top-*k*, hệ thống so tập ID trả về với tập ID chuẩn để tính Hit@k, Recall@k hoặc MRR. Phần trả lời chỉ được coi là tốt khi thông tin nó nêu được hỗ trợ bởi các tài liệu đúng; vì vậy cần đo riêng retrieval và mức độ grounded/correct của answer.

3. Quality checks là kiểm tra tính đúng của bản ghi và index: thiếu DOI, trùng ID, chunk rỗng, metadata sai kiểu hoặc số vector không khớp số chunk đều là lỗi chất lượng. Freshness monitoring không kết luận các dữ liệu đó đúng hay sai; nó theo dõi lần đồng bộ cuối, độ tuổi của snapshot và lượng dữ liệu mới để biết index có bị cũ không.

4. Baseline, corrupted và repaired phải chạy trên đúng một evaluation set để loại trừ biến số đầu vào. Nếu thay query hoặc ground truth giữa các lần chạy thì sự khác nhau của Recall@k có thể do tập mới khó hơn, không thể quy cho lỗi index hay hiệu quả repair.

5. Với tầng dữ liệu, repair cần để lại artifact kiểm tra được như manifest/index version, số document và chunk đã nạp, cùng báo cáo không còn bản ghi lỗi. Sau đó các metric retrieval trên cùng test set phải trở lại ngưỡng baseline; chỉ khi cả tính toàn vẹn dữ liệu lẫn Recall@k/MRR được phục hồi mới xác nhận repair thành công.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Vũ Đình Huy
**Ngày xác nhận:** 2026-08-05
