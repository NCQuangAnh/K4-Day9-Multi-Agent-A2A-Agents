# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Nguyễn Cao Quang Anh |
| MSSV            | 2A202601352 |
| Khóa/Lớp        | K4 |
| Vai trò chính   | Kiến trúc hệ thống & điều phối multi-agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Tầng agent & orchestration | `pipeline.py` — `CaseRunner`, `CoordinatorAgent`, `BaseAgent`, `Handoff`, `Fact` | `CaseInput` từ `input/EC_xxx.json` | `EvidenceBundle` + `output/EC_xxx.json` | Hoàn thành |
| Đăng ký & cấu hình model | `pipeline.py` — `MODEL_PROFILES`, `PROVIDERS`, `LLMClient` | Tên model khai báo cứng trong code, key từ `.env` | 7 agent chạy 5 họ model dense ≤10B | Hoàn thành |
| Tài liệu kiến trúc | `architecture.md`, `pipeline.md` | Yêu cầu README §7, §8 | Sơ đồ agent, quyền truy cập, luồng handoff | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Điều tra chênh lệch điểm chấm | Toàn nhóm | Xác định 4 nút thắt bằng cách đối chiếu output với bản đạt điểm cao hơn |
| Chạy và đóng gói bài nộp | Module của Nam Phương, Huy, Trung, Minh | `output.zip` 50 file, `logging/trace.jsonl`, `logging/metadata.json` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Dựng 7 agent với phạm vi dữ liệu tách bạch | `pipeline.py` | Coordinator và Policy không có tool đọc CSV | Đọc `logging/trace.jsonl`, đếm 250 handoff / 50 case |
| Cấu hình 7 model dense ≤10B thuộc 5 họ khác nhau | `pipeline.py::MODEL_PROFILES` | `logging/metadata.json` ghi model + parameter size + nguồn | `python run.py --all` rồi mở `metadata.json` |
| Chạy toàn trình 50 case | `run.py --all --workers 8` | 50 JSON + trace 902 dòng | `python run.py --validate` → `SAN SANG NOP` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

`logging/trace.jsonl` của lượt chạy chính thức: 902 dòng, gồm 50 `case_start`, 50 `plan`, 250 `handoff`, 50 `evidence_bundle`, 50 `policy_decision`, 50 `case_end` và 350 `llm_call` thành công trên 7 model khác nhau. Đây là bằng chứng cho thấy hệ thống thực sự có phân công và handoff giữa các agent, không phải một prompt duy nhất được đặt nhiều tên.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

README §7 nói rõ: không có điểm cho việc đặt tên nhiều agent nhưng toàn bộ xử lý nằm trong một prompt. Vấn đề là làm sao để việc phân vai là thật chứ không phải hình thức, trong khi vẫn không để LLM làm hỏng độ chính xác của các con số.

### Cách triển khai

Tách hai loại trách nhiệm. Số liệu do tool tất định trong `core.py` sinh ra; LLM chỉ điều phối, phát hiện fact thiếu/mâu thuẫn và kiểm chứng chéo. Quyền truy cập dữ liệu được cưỡng chế ở tầng code: mỗi agent nhận đúng một nhóm tool, Coordinator và Policy Agent không nhận tool dữ liệu nào nên chỉ thấy những gì specialist bàn giao qua `Handoff`. `Handoff` là hợp đồng giao tiếp duy nhất, gồm đúng 4 thành phần đề bài yêu cầu: ticket ID + câu hỏi, fact kèm `source_id`, fact thiếu/mâu thuẫn, đề xuất bước tiếp theo. `LLMClient` giữ một client cho mỗi provider, mọi lỗi đều nuốt và trả `None` để agent rơi về nhánh tất định — pipeline không bao giờ dừng vì LLM.

### Input, output và contract

| Thành phần              | Mô tả |
| ----------------------- | ----- |
| Input                   | `CaseInput` (case_id, claimed_order_id, investigation_scope, policy_version) |
| Output                  | `output/EC_xxx.json` đúng schema README §6, kèm dòng trace cho từng bước |
| Module phụ thuộc        | `core.DataStore`, `core.PolicyEngine`, `core.Assembler`, `core.Verifier` |
| Module sử dụng output   | `run.py` (ghi file, đóng gói zip, sinh metadata) |
| Điều kiện lỗi cần xử lý | LLM timeout / trả JSON hỏng / thiếu API key → rơi về nhánh tất định; `claimed_order_id` không tồn tại → sinh output rỗng hợp lệ và ghi cảnh báo `UNKNOWN_ORDER` |

### Cách xác minh

```bash
python run.py --all --workers 8
python run.py --validate
```

- **Kết quả mong đợi:** 50 file trong `output/`, 0 gate fail, trace ghi đủ 250 handoff
- **Kết quả thực tế:** Đúng như mong đợi. 350 lệnh gọi LLM thành công, 2 lỗi `JSONDecodeError` ở Verifier đã tự rơi về nhánh tất định mà không làm hỏng output.
- **Artifact/log:** `logging/trace.jsonl`, `logging/metadata.json` (không chứa secret; key nằm trong `.env` đã gitignore)

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần chọn model cho 7 agent dưới ràng buộc ≤10B tham số cho từng model.
- **Các phương án đã cân nhắc:** (a) Dùng một model duy nhất cho cả 7 agent. (b) Dùng model hosted của OpenAI/Gemini. (c) Dùng 5 họ model open-weights khác nhau.
- **Phương án đã chọn:** Phương án (c): Llama-3.1-8B, Gemma-3-4B, Qwen2.5-7B, Granite-4.1-8B, Ministral-8B.
- **Lý do:** Chỉ model open-weights mới có số tham số công bố chính thức để điền trung thực vào `metadata.json` — OpenAI và Gemini đều không công bố. Quan trọng hơn, Verifier phải khác họ model với Policy: nếu trùng model, nó sẽ mắc cùng loại lỗi và cho qua đúng sai lầm cần bắt.
- **Bằng chứng quyết định phù hợp:** Đã gọi thử từng slug trước khi chốt; 6/6 model trả JSON hợp lệ. `metadata.json` ghi được `parameter_size` kèm nguồn model card chính thức cho cả 7 agent.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Lượt chạy 50 case treo ở 31/50. Tiến trình Python còn sống nhưng chỉ dùng 15,6 giây CPU, `output/` và `logging/trace.jsonl` không tăng thêm dòng nào.
- **Lệnh hoặc bước tái hiện:** `python run.py --all --workers 8` với `policy` gán model `qwen/qwen3.5-9b`.
- **Nguyên nhân gốc:** `qwen3.5-9b` có độ trễ ~8 giây mỗi lệnh gọi, gấp 9 lần các model khác. Cộng với `timeout=45s` và 2 lần retry, một lệnh gọi treo có thể chiếm luồng tới hơn 2 phút và làm nghẽn cả pool.
- **Cách xử lý:** Đổi model của Policy Agent sang `ibm-granite/granite-4.1-8b` (đo được ~0,9 giây), giảm `timeout` xuống 20 giây và `retries` xuống 1 để một provider treo thất bại nhanh rồi rơi về nhánh tất định.
- **Cách xác minh sau khi sửa:** Chạy lại `python run.py --all --workers 8` → hoàn tất 50 case trong 161,6 giây, 0 gate fail.
- **Điều học được:** Trong hệ thống nhiều luồng gọi mạng, độ trễ đuôi quan trọng hơn độ trễ trung bình. Timeout dài cộng retry nhiều lần biến một model chậm thành điểm nghẽn của cả hệ thống, và triệu chứng nhìn giống hệt treo vô hạn.

## 7. Hiểu biết về luồng end-to-end

Nội dung mục này trả lời 5 câu hỏi end-to-end của bài lab RAG.

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. Luồng được tách thành các bước rõ ràng: collector gọi Crossref, normalizer chuẩn hóa metadata, chunker tạo đơn vị tìm kiếm, embedding service sinh vector và index service lưu vector cùng document ID. Thiết kế này giúp các bước giao tiếp bằng artifact có thể kiểm tra được, đồng thời truy vấn đi theo chiều ngược lại: query embedding → top-*k* chunks → context cho mô hình trả lời.

2. Evaluation set đóng vai trò contract cho toàn pipeline. Orchestrator chạy từng query, nhận danh sách top-*k* document IDs từ retriever và so với ground truth để đo Hit@k/Recall@k; answer evaluator sau đó kiểm tra câu trả lời có trả lời đúng câu hỏi và bám evidence hay không. Hai phép đo tách biệt giúp biết lỗi nằm ở retrieval hay generation.

3. Quality checks là các điều kiện chặn ở bước ingest/index, như contract metadata, độ phủ embedding và liên kết ID giữa chunk với document. Freshness monitoring là tín hiệu vận hành chạy theo thời gian, cảnh báo snapshot Crossref quá cũ hoặc job ingest bị chậm. Một index có thể fresh nhưng vẫn lỗi quality, hoặc chất lượng tốt nhưng đã lỗi thời.

4. Giữ nguyên test set tạo một đường chuẩn cố định qua ba trạng thái hệ thống. Nhờ đó dashboard metric phản ánh tác động của corruption và repair thay vì phản ánh sự thay đổi về phân bố câu hỏi hoặc số lượng ground-truth documents.

5. Repair được chấp nhận khi các artifact phiên bản mới — log job, manifest index và báo cáo evaluation — khớp với nhau, không còn lỗi đã phát hiện. Các metric retrieval và answer quality trên test set cố định phải đạt mục tiêu hoặc trở về gần baseline; nếu chỉ rebuild index mà score chưa hồi phục thì pipeline chưa được xem là repaired.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Cao Quang Anh
**Ngày xác nhận:** 2026-08-05
