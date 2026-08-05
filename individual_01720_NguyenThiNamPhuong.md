# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung               |
| --------------- | ---------------------- |
| Họ và tên       | Nguyễn Thị Nam Phương  |
| MSSV            | 01720                  |
| Khóa/Lớp        | K4                     |
| Vai trò chính   | Lead System Architect & Multi-Agent Developer |
| Ngày hoàn thành | 2026-08-05             |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái                            |
| ------------------ | ------------------ | -------------- | ----------------- | ------------------------------------- |
| **Data Access Layer** | `data_loader.py` (`OlistData`) | 9 file CSV dữ liệu Olist trong `data/` | Global Singleton với O(1) indexed lookup | Hoàn thành |
| **Agent Framework & Integration** | `agent_base.py`, `main.py` | Groq API Key (`.env`), Input JSON | Tracing system (`trace.jsonl`), Orchestration pipeline | Hoàn thành |
| **Policy & Business Logic Engine** | `agents/policy_agent.py` | Kết quả phân tích từ các Sub-Agents | Decision matrix EC_POLICY_V2 (Primary/Secondary issues, Refund, Actions) | Hoàn thành |
| **Coordinator & Verification** | `agents/coordinator_agent.py`, `agents/verifier_agent.py` | Case input JSON & Draft agent assessment | Final Output JSON schema validation, evidence ID resolution, confidence score | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                 |
| ------------------------- | ----------------------------- | ----------------------- |
| **Fix Windows Encoding Issue** | Pipeline execution (`main.py`) | Sửa lỗi `UnicodeEncodeError` cp1252 trên Windows console |
| **Documentation & Architecture** | Root repository | Tạo `architecture.md`, `metadata.json`, `requirements.txt`, `.gitignore` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao          | Cách xác minh   |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Triển khai 7 Agents chuyên biệt | `agents/*.py` | 7 modules: Coordinator, Customer, OrderProduct, Payment, Delivery, Policy, Verifier | Direct python imports & execution |
| Chạy nghiệm thu 50 Cases | `output/EC_001.json` - `EC_050.json` | 50 file JSON chuẩn schema | `python main.py` |
| Ghi nhận Trace Log | `logging/trace.jsonl`, `logging/metadata.json` | 744 trace entries log lại toàn bộ lịch sử xử lý | Inspection of `trace.jsonl` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Hệ thống xử lý hoàn chỉnh 50/50 cases đạt tỉ lệ thành công 100% với thời gian xử lý trung bình 2.96 giây/case. File `logging/trace.jsonl` ghi nhận đầy đủ 744 sự kiện tương tác và handoff giữa 7 agents.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Trong thực tế khiếu nại e-commerce, thông tin khách hàng cung cấp thường thiếu hoặc không khách quan. Hệ thống cần đối soát đồng thời nhiều nguồn dữ liệu (Orders, Items, Payments, Customers, Products, Sellers, Delivery timestamps) để đưa ra kết luận chính xác, công bằng và tuân thủ tuyệt đối quy tắc nghiệp vụ `EC_POLICY_V2`.

### Cách triển khai

1. **Phân tách trách nhiệm (Separation of Concerns)**: Mỗi agent chỉ đảm nhận 1 miền dữ liệu.
2. **Hybrid Deterministic + LLM Architecture**: 
   - Phân tích ngày giờ, đối soát tài chính, phân loại lỗi được thực hiện bằng Python thuần (Deterministic) để đảm bảo độ chính xác 100%, không bị hallucination.
   - LLM (Groq `llama-3.1-8b-instant`, 8B params) được sử dụng ở tầng Coordinator để đánh giá chất lượng bằng chứng và tính toán `confidence` score.
3. **Data Layer Indexing**: Tải 9 file CSV 1 lần duy nhất vào bộ nhớ và tạo cấu hình Indexing (HashMap) theo Primary Keys giúp tra cứu thông tin O(1).

### Input, output và contract

| Thành phần              | Mô tả                                  |
| ----------------------- | -------------------------------------- |
| Input                   | Case Input JSON chứa `claimed_order_id`, `investigation_scope`, `policy_version` |
| Output                  | Output JSON chuẩn Schema gồm `case_assessment`, `affected_entities`, `delivery_analysis`, `payment_reconciliation`, `root_cause_analysis`, `evidence_ids`, `financial_resolution`, `resolution_actions` |
| Module phụ thuộc        | `data_loader.py`, `agent_base.py`, Groq SDK |
| Module sử dụng output   | `main.py` (Main Pipeline) & Verifier Agent |
| Điều kiện lỗi cần xử lý | Order bị hủy (`canceled`), đơn hết hàng (`unavailable`), seller bàn giao trễ, giao hàng trễ do vận chuyển, thanh toán chia nhỏ (`split_payment`) |

### Cách xác minh

```bash
python main.py
```

- **Kết quả mong đợi:** Xử lý thành công 50/50 case, không crash, tạo đủ 50 file JSON trong `output/` và ghi 744 trace entries trong `logging/trace.jsonl`.
- **Kết quả thực tế:** 50/50 cases succeeded trong 147.8 giây (0 failed).
- **Artifact/log:** [trace.jsonl](file:///d:/VinUni/Lab09/K4-Day9-Multi-Agent-A2A-Agents/logging/trace.jsonl), [metadata.json](file:///d:/VinUni/Lab09/K4-Day9-Multi-Agent-A2A-Agents/logging/metadata.json)

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Lựa chọn phương pháp suy luận cho bài toán xử lý đối soát dữ liệu và phân loại lỗi theo `EC_POLICY_V2`.
- **Các phương án đã cân nhắc:** 
  1. *Phương án A (Pure LLM)*: Đưa toàn bộ CSV data vào prompt và yêu cầu LLM tự tính toán thời gian, tiền bạc và tự phân loại.
  2. *Phương án B (Hybrid Multi-Agent - Selected)*: Dùng Python cho tính toán logic/số liệu chính xác, dùng LLM ở tầng Coordinator/Verifier cho lý luận và đánh giá confidence.
- **Phương án đã chọn:** Phương án B (Hybrid Multi-Agent).
- **Lý do:** Tránh hoàn toàn hiện tượng Hallucination của LLM đối với các phép tính số liệu thập phân (BRL) và chênh lệch giờ (hours variance). Tăng tốc độ xử lý lên ~3s/case và đảm bảo tính nhất quán 100% với `EC_POLICY_V2`.
- **Bằng chứng quyết định phù hợp:** Kết quả đối soát tài chính `difference_brl` đạt độ chính xác sai số `0.00 BRL` tuyệt đối trên toàn bộ 50 cases test.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713' in position 2: character maps to <undefined>`
- **Lệnh hoặc bước tái hiện:** `python main.py` chạy trên Windows Terminal (Standard CP1252 codepage).
- **Nguyên nhân gốc:** Console mặc định của Windows không hỗ trợ ký tự UTF-8 checkmark (`✓` và `✗`) trong hàm `print()`.
- **Cách xử lý:** Thay thế các ký tự Unicode checkmark bằng chuỗi ASCII tiêu chuẩn `[OK]` và `[FAIL]` trong `main.py`.
- **Cách xác minh sau khi sửa:** Chạy lại `python main.py` - script thực thi thành công không lỗi, xuất ra console sạch đẹp.
- **Điều học được:** Khi viết CLI tool trên Windows, cần chú ý tương thích bảng mã console hoặc cấu hình mã hóa stdout bằng `sys.stdout.reconfigure(encoding='utf-8')`.

## 7. Hiểu biết về luồng end-to-end

1. **Dữ liệu đi từ CSV đến Output JSON như thế nào?**
   Dữ liệu 9 file CSV được `data_loader.py` load và index vào RAM. Khi nhận `claimed_order_id` từ case input, Coordinator dispatches công việc đến CustomerAgent, OrderProductAgent, PaymentAgent và DeliveryAgent để truy vấn các bảng CSV tương ứng. Kết quả được chuyển qua PolicyAgent để áp dụng bộ quy tắc `EC_POLICY_V2` và cuối cùng VerifierAgent kiểm chứng schema + evidence IDs trước khi ghi ra file JSON.

2. **Evidence IDs đóng vai trò gì trong việc kiểm chứng?**
   `evidence_ids` là danh sách các mã chứng cứ trực tiếp từ dữ liệu (vd: `order:<id>`, `item:<id>:1`, `payment:<id>:1`, `seller:<id>`, `policy:<code >`). Chúng cho phép hệ thống chấm điểm tự động đối soát và xác minh từng khẳng định của Agent dựa trên dữ liệu thực tế mà không sợ bị hallucination.

3. **Chức năng của VerifierAgent khác với Tracing monitoring ở điểm nào?**
   - *VerifierAgent*: Đảm bảo tính hợp lệ của dữ liệu đầu ra (Schema Validation, giới hạn mảng, định dạng Evidence ID, null handling, confidence bounds).
   - *Tracing Monitoring (`trace.jsonl`)*: Ghi lại lịch sử hoạt động, thời gian phản hồi, số token tiêu tốn và nhật ký handoff giữa các agent để phục vụ kiểm toán và debug.

4. **Vì sao phải áp dụng EC_POLICY_V2 theo đúng thứ tự ưu tiên?**
   Vì một đơn hàng có thể gặp nhiều vấn đề cùng lúc (ví dụ vừa bị hủy vừa bị giao muộn). Bộ quy tắc có thứ tự ưu tiên rõ ràng (1. Canceled -> 2. Unavailable -> 3. Late Seller -> 4. Late Logistics -> 5. Valid Split -> 6. Unsupported Claim) để đảm bảo xác định đúng nguyên nhân gốc rễ và bên chịu trách nhiệm cao nhất.

5. **Processing / Verification được xem là thành công dựa trên artifact và metric nào?**
   - Tạo đủ 50/50 file JSON trong thư mục `output/` trùng tên với `input/`.
   - File JSON hợp lệ 100% theo Output Schema đề bài quy định.
   - `trace.jsonl` ghi lại đầy đủ luồng xử lý thực tế của lượt chạy mới nhất.
   - File `metadata.json` chứa thông tin model (`llama-3.1-8b-instant`, 8B params).

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Thị Nam Phương  
**Ngày xác nhận:** 2026-08-05
