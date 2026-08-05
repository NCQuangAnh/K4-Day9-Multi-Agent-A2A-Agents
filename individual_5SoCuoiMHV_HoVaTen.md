## Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Vũ Đình Huy |
| MSSV | 2A202601288 |
| Lớp | E403 |
| Vai trò chính | Thiết kế pipeline, đối soát chính sách và kiểm chứng output |

## Phần việc phụ trách

| Module | Trách nhiệm | Kết quả bàn giao |
| --- | --- | --- |
| `pipeline.py` | Join dữ liệu Olist, tính delivery/payment và áp dụng `EC_POLICY_V2` | 50 JSON trong `output/` |


## Cách triển khai

Pipeline nhận `claimed_order_id` từ từng input, sau đó tách dữ liệu thành các
handoff có cấu trúc: customer history, order/product, payment reconciliation
và delivery analysis. Policy stage ưu tiên theo `EC_POLICY_V2`: đơn cancelled
hoặc unavailable đã thanh toán, giao trễ do seller, giao trễ do logistics,
split payment hợp lệ và cuối cùng là claim giao trễ không được hỗ trợ.

Để tránh false positive, evidence chỉ được tạo từ ID có thể truy vết trực tiếp
trong CSV: order, item, payment, seller chịu trách nhiệm và policy root cause.
Verifier kiểm tra tên case, giới hạn số phần tử, confidence và cấu trúc ZIP
trước khi tạo file nộp.

## Quyết định kỹ thuật

Tính toán tiền, chênh lệch giao hàng và phân loại policy được giữ theo quy tắc
xác định thay vì để model sinh số liệu. Cách này giúp mọi giá trị trong output
đối chiếu được với CSV, đặc biệt cho refund và evidence ID. Lượt tạo output
hiện tại không gọi model sinh ngôn ngữ; toàn bộ kết quả được tái lập trực tiếp
từ dữ liệu nguồn và chính sách nghiệp vụ.

## Kiểm chứng

- `output/` có 50 file từ `EC_001.json` đến `EC_050.json`.
- `output.zip` có đúng 50 entry `output/EC_001.json` đến `output/EC_050.json`.


## Cam kết

Tôi đã rà soát các artifact được nêu trong báo cáo, không đưa API key hoặc
secret vào source/ZIP, và có thể giải thích luồng dữ liệu từ input đến output.
