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

Nội dung mục này trả lời 5 câu hỏi end-to-end của bài lab RAG.

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. Crossref là nguồn đầu vào; từng bản ghi được chuẩn hóa, gắn document ID và tách thành các chunk có provenance như DOI và vị trí trong tài liệu. Sau bước embedding, vector index lưu vector cùng metadata đó. Khi truy vấn, retriever trả top-*k* chunk kèm ID nguồn, nên câu trả lời có thể lần theo đúng document thay vì dùng context không rõ xuất xứ.

2. Evaluation set cung cấp luồng query lặp lại được. Ground-truth document IDs là contract cho retriever: hệ thống đối chiếu chúng với ID trong top-*k* để tính Hit@k/Recall@k hoặc MRR. Sau handoff retrieval → answer, evaluator kiểm tra câu trả lời có bám các nguồn đúng và giải đáp đúng yêu cầu hay không, nên retrieval score và answer score được theo dõi riêng.

3. Quality checks rà soát artifact và liên kết giữa các bước: record hợp lệ, chunk không rỗng, embedding tồn tại, ID từ index tra được về Crossref. Freshness monitoring ghi nhận nhịp cập nhật, timestamp và độ trễ để phát hiện index đã cũ. Check chất lượng có thể pass dù dữ liệu cũ, vì vậy vẫn cần monitoring freshness độc lập.

4. Dùng một test set cố định bảo toàn khả năng trace chênh lệch: cùng query và ground truth sẽ cho thấy rõ corruption làm hỏng bước nào, và repair có khôi phục được không. Đổi test set giữa các lượt sẽ không còn cơ sở để so sánh trực tiếp metric trước/sau.

5. Repair thành công phải có artifact truy vết được, như log rebuild index, manifest phiên bản và báo cáo kiểm tra không còn lỗi; đồng thời evaluation log trên test set cố định phải cho thấy Hit@k/Recall@k và answer quality đạt lại ngưỡng mục tiêu. Chỉ có artifact hoặc chỉ có một metric tốt đều chưa đủ để kết luận repair đã hoàn tất.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Lê Quang Trung
**Ngày xác nhận:** 2026-08-05
