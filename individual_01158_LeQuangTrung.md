# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Lê Quang Trung |
| MSSV            | 2A202601158 |
| Khóa/Lớp        | K4 |
| Vai trò chính   | Agent chuyên trách & cơ chế handoff có cấu trúc |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| 4 agent chuyên trách | `pipeline.py` — `CustomerAgent`, `OrderProductAgent`, `PaymentAgent`, `DeliveryAgent` | Câu hỏi từ Coordinator + `claimed_order_id` | Một `Handoff` mỗi agent | Hoàn thành |
| Bộ tool có phạm vi | `core.py` — `CustomerTools`, `OrderProductTools`, `PaymentTools`, `DeliveryTools` | `DataStore` | `CustomerFacts`, `OrderProductFacts`, `PaymentFacts`, `DeliveryFacts` | Hoàn thành |
| Ghi trace | `pipeline.py` — `Tracer`, `Handoff.to_json` | Sự kiện từ mọi agent | `logging/trace.jsonl` | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Song song hoá theo case | Module orchestration của Quang Anh | Thêm lock cho `Tracer`, rút thời gian chạy 50 case từ ~13 phút xuống 161 giây |
| Cung cấp dữ liệu cho Policy | Module của Nam Phương | `EvidenceBundle` gộp từ 4 handoff |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Cưỡng chế phạm vi dữ liệu ở tầng code | 4 lớp `*Tools` trong `core.py` | Payment Agent thấy `price`/`freight_value` nhưng không thấy `seller_id` | Đọc chữ ký hàm và docstring từng lớp tool |
| Handoff đủ 4 thành phần đề bài yêu cầu | `Handoff`, `Fact` | 250 handoff / 50 case trong trace | `python run.py --all` rồi đếm sự kiện `handoff` |
| Tính variance giao hàng theo từng seller | `DeliveryTools.analyse` | `seller_handoff_analysis` + `late_handoff_seller_ids` | Đối chiếu độc lập bằng pandas, 0 sai lệch |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

`logging/trace.jsonl` chứa 250 sự kiện `handoff` cho 50 case — đúng 5 handoff mỗi case (4 specialist gửi về Coordinator, 1 từ Policy sang Verifier). Mỗi dòng có đủ `case_id`, `question`, `from`, `to`, danh sách `facts` với `source_id`, `missing_or_conflicting` và `suggested_next`. Đây là artifact chứng minh luồng handoff có thật và kiểm tra được.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Đề yêu cầu handoff phải chứa fact kèm ID nguồn, fact thiếu hoặc mâu thuẫn, và đề xuất bước tiếp theo. Khó ở chỗ: để LLM viết phần nhận xét thì nó dễ bịa ra vấn đề không tồn tại, còn nếu bỏ LLM thì handoff chỉ còn là bản sao dữ liệu.

### Cách triển khai

Mỗi agent lấy fact từ tool tất định, gắn `source_id` dựng được từ CSV, rồi mới đưa danh sách fact đó cho LLM để viết `missing_or_conflicting` và `suggested_next`. System prompt nói rõ LLM không được thay đổi giá trị fact, và chỉ được liệt kê fact có giá trị `null` hoặc mảng rỗng, hoặc hai fact mâu thuẫn trực tiếp — cấm suy diễn và cấm coi một giá trị hợp lệ là 'thiếu'. Nếu LLM lỗi thì rơi về danh sách suy ra tất định từ các fact rỗng. `Tracer` ghi mọi sự kiện qua một lock vì các case chạy song song; không có lock thì các dòng JSON sẽ đan xen và hỏng file.

### Input, output và contract

| Thành phần              | Mô tả |
| ----------------------- | ----- |
| Input                   | `CaseInput` + câu hỏi riêng cho từng domain do Coordinator giao |
| Output                  | `Handoff` gồm case_id, question, from, to, facts (mỗi fact có `source_id`), missing_or_conflicting, suggested_next, ts |
| Module phụ thuộc        | `core.DataStore` (gián tiếp qua các lớp `*Tools`), `pipeline.LLMClient` |
| Module sử dụng output   | `CoordinatorAgent._gather` (gộp thành `EvidenceBundle`), `Tracer` (ghi `trace.jsonl`) |
| Điều kiện lỗi cần xử lý | LLM trả JSON hỏng hoặc timeout → dùng danh sách `missing` suy ra tất định; `carrier_handoff_at` null → không kết luận seller bàn giao trễ |

### Cách xác minh

```bash
python run.py --all --workers 8
python -c "import json;print(sum(1 for l in open('logging/trace.jsonl',encoding='utf-8') if json.loads(l)['event']=='handoff'))"
```

- **Kết quả mong đợi:** 250 sự kiện handoff cho 50 case
- **Kết quả thực tế:** Đúng 250. Trace tổng 902 dòng, không có dòng nào hỏng dù chạy 8 luồng song song.
- **Artifact/log:** `logging/trace.jsonl`

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Ban đầu handoff báo 'thiếu dữ liệu' ở 52/60 lượt trong self-test, phần lớn là do LLM bịa ra.
- **Các phương án đã cân nhắc:** (a) Bỏ hẳn phần LLM, chỉ liệt kê tất định các fact rỗng. (b) Giữ LLM nhưng siết prompt bằng quy tắc cụ thể về cái gì được coi là 'thiếu'.
- **Phương án đã chọn:** Phương án (b).
- **Lý do:** Bỏ hẳn LLM thì handoff mất đi phần giá trị thật là nhận xét về mâu thuẫn giữa các fact. Vấn đề nằm ở prompt quá mở chứ không phải ở việc dùng LLM.
- **Bằng chứng quyết định phù hợp:** Sau khi thêm quy tắc — chỉ liệt kê fact có giá trị `null`/mảng rỗng hoặc mâu thuẫn trực tiếp, và nói rõ rằng order không có item hay order chưa giao đều là trường hợp hợp lệ trong dữ liệu Olist — số handoff báo thiếu giảm từ 52/60 xuống 25/60.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Khi bật `--workers 8`, một số dòng trong `trace.jsonl` bị cắt ngang và đan vào nhau, khiến `json.loads` lỗi khi đọc lại.
- **Lệnh hoặc bước tái hiện:** `python run.py --all --workers 8` rồi đọc từng dòng `logging/trace.jsonl` bằng `json.loads`.
- **Nguyên nhân gốc:** `Tracer` ghi trực tiếp vào file handle từ nhiều luồng. Hai lệnh `write` từ hai luồng có thể xen kẽ nhau giữa chừng một dòng.
- **Cách xử lý:** Gom việc tạo chuỗi JSON và ghi file vào một hàm `_write` duy nhất, bọc bằng `threading.Lock`; `bump` đếm counter cũng dùng chung lock đó.
- **Cách xác minh sau khi sửa:** Chạy lại với 8 luồng, đọc toàn bộ 902 dòng bằng `json.loads` → không dòng nào lỗi.
- **Điều học được:** Song song hoá không chỉ là bọc `ThreadPoolExecutor`. Mọi tài nguyên dùng chung — file handle, biến đếm — đều phải rà lại; lỗi kiểu này không xuất hiện khi chạy một luồng nên rất dễ lọt.

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

**Họ và tên:** Lê Quang Trung
**Ngày xác nhận:** 2026-08-05
