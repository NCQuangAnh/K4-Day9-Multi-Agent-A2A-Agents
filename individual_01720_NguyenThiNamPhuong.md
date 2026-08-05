# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Nguyễn Thị Nam Phương |
| MSSV            | 2A202601720 |
| Khóa/Lớp        | K4 |
| Vai trò chính   | Policy engine & phân loại nghiệp vụ (EC_POLICY_V2) |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Rule engine EC_POLICY_V2 | `core.py` — `PolicyEngine.decide`, `_primary_issue`, `_secondary_issues`, `_refund`, `_responsible_parties`, `_actions` | `EvidenceBundle` từ Coordinator | `PolicyDecision` (primary, secondary, refund, parties, actions, root cause) | Hoàn thành |
| Agent áp policy | `pipeline.py` — `PolicyAgent.decide`, `_llm_proposal` | `EvidenceBundle` + 4 handoff | Quyết định cuối + dòng trace `policy_decision` | Hoàn thành |
| Bảng ánh xạ hằng số nghiệp vụ | `core.py` — `ROOT_CAUSE_OF`, `PRIMARY_ACTION_OF`, `SECONDARY_ORDER` | README §4 | 6 primary issue ↔ 6 root cause ↔ 6 action chính | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Bản cài đặt độc lập để đối chiếu | Toàn nhóm | Hai bản độc lập trùng khớp trên 50 case ở mọi field nghiệp vụ, xác nhận cách đọc policy là đúng |
| Rà soát điều kiện kích hoạt action | Module Verifier của Tuấn Minh | Bổ sung gate 9 kiểm tra thứ tự action và ngoại lệ `valid_split_payment` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Cài 6 nhánh policy theo đúng thứ tự ưu tiên | `PolicyEngine._primary_issue` | Phân bố 8/6/10/10/8/8 trên 50 case | Đối chiếu độc lập bằng pandas thuần, 0 sai lệch |
| Kiểm tra không case nào rơi vào fallback | Script phân tích | 0/50 case gán bằng fallback — cả 50 đều khớp điều kiện tường minh | So từng case với bảng README §4 |
| Cơ chế LLM đề xuất ‖ rule engine quyết định | `PolicyAgent.decide` | Tỉ lệ đồng thuận ghi vào trace | Đếm `policy_discrepancy` trong `trace.jsonl` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Bảng phân bố `primary_issue` trên 50 case: `canceled_order_paid` 8, `unavailable_order_paid` 6, `late_delivery_seller` 10, `late_delivery_logistics` 10, `valid_split_payment` 8, `unsupported_late_claim` 8. Kiểm tra thêm cho thấy **0/50 case được gán bằng fallback** — mỗi case đều thoả một điều kiện tường minh trong README §4, kể cả `unsupported_late_claim` vốn có điều kiện riêng chứ không phải nhánh mặc định.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

`EC_POLICY_V2` là bảng quyết định có thứ tự ưu tiên, nhưng README không nói rõ điều gì xảy ra khi một case thoả nhiều điều kiện cùng lúc, và cũng không cho điều kiện kích hoạt của các action bổ sung. Sai một nhánh là mất khoảng 8 case, tức ~16% tổng điểm.

### Cách triển khai

Cài `_primary_issue` theo đúng thứ tự liệt kê trong README, khớp đầu tiên thì dừng — nên một order vừa giao trễ vừa có split payment hợp lệ sẽ được xếp vào nhánh giao trễ. `_secondary_issues` xét theo thứ tự cố định `multi_item_order → multi_seller_order → split_payment → repeat_customer → multiple_categories` và không phụ thuộc `investigation_scope`, vì README §4 định nghĩa chúng thuần theo điều kiện dữ liệu. Sáu root-cause code ánh xạ một-một với sáu primary issue, và ví dụ §6 chỉ có một phần tử trong `ranked_causes`, nên mỗi case đúng một cause với `rank: 1`. `_actions` đặt action chính lên đầu rồi thêm action bổ sung theo đúng thứ tự README, với ngoại lệ không thêm `verify_payment_allocation` khi primary là `valid_split_payment`.

### Input, output và contract

| Thành phần              | Mô tả |
| ----------------------- | ----- |
| Input                   | `EvidenceBundle` — order_status, tổng payment, số payment row, reconciled, các mốc giao hàng, danh sách seller bàn giao trễ |
| Output                  | `PolicyDecision` — primary_issue, secondary_issues, case_status, responsible_parties, root_cause_code, recommended_refund, resolution_actions |
| Module phụ thuộc        | `CustomerTools`, `OrderProductTools`, `PaymentTools`, `DeliveryTools` (qua handoff, không đọc CSV trực tiếp) |
| Module sử dụng output   | `core.Assembler` (dựng output), `core.Verifier` (gate 8, 9, 10) |
| Điều kiện lỗi cần xử lý | Order không có item row → refund freight bằng 0; order chưa từng giao → không thoả điều kiện giao trễ; payment không khớp → không vào nhánh `valid_split_payment` |

### Cách xác minh

```bash
python run.py --selftest
python run.py --unittest
```

- **Kết quả mong đợi:** 12/12 case self-test khớp nhánh policy mong đợi; 5/5 phép tính khớp ví dụ README §6
- **Kết quả thực tế:** Cả hai đều `TAT CA PASS`. Self-test phủ đủ 6 nhánh policy và 6 edge case, mỗi case dùng `order_id` có thật quét ra từ CSV.
- **Artifact/log:** `selftest/output/`, `selftest/trace.jsonl`

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** README định nghĩa secondary issue thuần theo điều kiện dữ liệu, nhưng input lại có `investigation_scope` bật/tắt customer history và product context.
- **Các phương án đã cân nhắc:** (a) Tắt scope thì bỏ luôn secondary issue tương ứng. (b) Luôn tính đủ secondary issue, scope chỉ chặn ở khâu xuất `customer_context` và `product_context`.
- **Phương án đã chọn:** Phương án (b).
- **Lý do:** README §4 định nghĩa `repeat_customer` và `multiple_categories` thuần theo điều kiện dữ liệu, không hề nhắc tới scope. Scope quyết định *báo cáo cái gì*, không quyết định *đánh giá thế nào*. Để scope ảnh hưởng sang phần đánh giá là lẫn lộn hai việc khác nhau.
- **Bằng chứng quyết định phù hợp:** Kiểm tra 50 input thật cho thấy cả 50 đều có `investigation_scope` là `(true, true)`, nên lựa chọn này không gây rủi ro trên bộ đề thực tế, đồng thời vẫn đúng về mặt nguyên tắc nếu đề đổi.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Policy Agent chỉ đồng thuận với rule engine 7/12 case trong self-test. LLM liên tục trả `unsupported_late_claim` ngay cả khi `delivery_variance_hours = 286.4` và `late_handoff_seller_ids` không rỗng.
- **Lệnh hoặc bước tái hiện:** `python run.py --selftest` rồi đếm sự kiện `policy_discrepancy` trong `selftest/trace.jsonl`.
- **Nguyên nhân gốc:** Prompt gửi cho LLM chỉ có số liệu thô (timestamp, số giờ) và bắt model tự suy ra 'giao trễ' hay 'seller trễ'. Model cỡ 8B suy diễn nhiều bước như vậy không ổn định nên rơi về nhánh mặc định.
- **Cách xử lý:** Đưa thẳng các điều kiện đã suy diễn sẵn dưới dạng boolean vào prompt: `delivered_later_than_estimated`, `at_least_one_seller_handed_off_late`, `payment_reconciled_within_0_10_brl`, và ghi rõ trong system prompt rằng chỉ cần áp thẳng, không tự suy diễn lại từ timestamp.
- **Cách xác minh sau khi sửa:** Chạy lại `python run.py --selftest` → đồng thuận tăng từ 7/12 lên 11/12, độ trễ trung bình cũng giảm từ 2816 ms xuống 2229 ms.
- **Điều học được:** Với model nhỏ, chuyển gánh nặng suy diễn từ model sang prompt hiệu quả hơn nhiều so với đổi sang model lớn hơn. Giữ lại 1/12 bất đồng là có chủ đích: đồng thuận 100% sẽ khiến nhánh LLM vô nghĩa như một tín hiệu kiểm chứng.

## 7. Hiểu biết về luồng end-to-end

Nội dung mục này trả lời 5 câu hỏi end-to-end của bài lab RAG.

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. Dữ liệu Crossref được lấy về, chuẩn hóa và gắn document ID trước khi tách thành các chunk có metadata nguồn. Embedding model chuyển từng chunk thành vector, còn vector index lưu vector song song với ID và DOI. Nhờ vậy retriever có thể trả các nguồn liên quan để mô hình sinh câu trả lời có căn cứ thay vì chỉ dựa vào kiến thức sẵn có.

2. Evaluation set định nghĩa các tình huống cần đánh giá, còn ground-truth document IDs định nghĩa nguồn hợp lệ cho từng tình huống. Nếu tài liệu chuẩn xuất hiện trong top-*k*, metric retrieval tăng; sau đó answer quality đánh giá quyết định/câu trả lời có đúng và được evidence hỗ trợ không. Cần đọc hai nhóm metric cùng nhau để không tối ưu retrieval mà bỏ qua tính đúng của câu trả lời.

3. Quality checks tập trung vào điều kiện dữ liệu có đủ tin cậy để ra quyết định: metadata đầy đủ, ID nhất quán, không trùng lặp và embedding/index không thiếu. Freshness monitoring tập trung vào rủi ro dữ liệu quá hạn: thời gian từ lần fetch Crossref gần nhất, độ trễ job và snapshot age. Đây là hai loại kiểm soát bổ sung, không thay thế nhau.

4. Một policy đánh giá công bằng chỉ thay đổi đúng một biến mỗi lần. Khi dùng cùng test set, chênh lệch giữa baseline, corrupted và repaired mới có thể quy cho thay đổi dữ liệu/index; dùng tập khác sẽ làm mất khả năng so sánh và khó đặt ngưỡng pass/fail.

5. Repair chỉ được phê duyệt khi có artifact chứng minh nguyên nhân đã được xử lý, chẳng hạn báo cáo quality-check sạch, version index mới và log chạy evaluation. Quyết định cuối dựa trên metric: các chỉ số retrieval phải quay lại ngưỡng baseline/target và answer score phải giữ hoặc phục hồi theo ngưỡng đã công bố.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Thị Nam Phương
**Ngày xác nhận:** 2026-08-05
