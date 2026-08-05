# RUNBOOK — quy trình chạy ngày thi

> Hệ thống đã dựng và kiểm chứng xong **trước** Checkpoint 1.
> Tài liệu này là các lệnh cần gõ khi input thật xuống, theo đúng thứ tự.

---

## 0. Chuẩn bị một lần (làm trước 13h)

```bash
pip install -r requirements.txt
cp .env.example .env          # rồi điền OPENROUTER_API_KEY
```

Kiểm tra hệ thống còn lành:

```bash
python run.py --unittest      # 5 phép tính lấy từ ví dụ README §6
python run.py --selftest      # 12 case sinh từ CSV thật, phủ 6 nhánh + 6 edge case
```

Cả hai phải in `TAT CA PASS`. Nếu không, **đừng chạy tiếp** — sửa nguyên nhân trước.

---

## 1. Khi input thật xuống (13h–13h30)

Giải nén 50 file `EC_001.json … EC_050.json` vào `input/`, rồi:

```bash
python run.py --all
```

Lệnh này ghi:

| Artifact | Nội dung |
|---|---|
| `output/EC_001.json … EC_050.json` | Bài nộp |
| `logging/trace.jsonl` | Ghi **mới** (mode `w`), đúng yêu cầu "chỉ cần lượt chạy mới nhất" |
| `logging/metadata.json` | Model, parameter size, framework, runtime, thống kê lượt chạy |

Kiểm tra `metadata.json` có `"run_type": "official"`. Nếu là `"simulation"` thì bạn đang chạy nhầm thư mục input.

---

## 2. Kiểm tra trước khi nộp

```bash
python run.py --validate
```

Phải in `SAN SANG NOP`. Lệnh này kiểm tra:

- đúng **50** file `EC_*.json`
- không có file lạ trong `output/`
- mọi file qua đủ **10 gate** (schema, evidence tồn tại, giới hạn mảng, null handling, làm tròn, timestamp, nhất quán status, thứ tự action, thứ tự secondary)

---

## 3. Đóng gói

```bash
python run.py --zip
```

Sinh **`output.zip`** chứa **phẳng 50 file JSON**, không kèm source code, không kèm `.env` (README §9.2).

---

## 4. Commit source code

README §8.3 yêu cầu commit toàn bộ source **trước** khi nộp zip.

```bash
git add -A
git commit -m "feat: multi-agent dispute resolution pipeline for 50 cases"
git push
```

`.gitignore` đã chặn `.env`. Kiểm tra lại cho chắc:

```bash
git status --short | grep -i env      # phải không ra dòng nào ngoài .env.example
```

---

## 5. Khi một case bị lỗi

**Không sửa tay JSON.** Quy trình đúng:

1. Đọc `logging/trace.jsonl`, tìm dòng `gate_fail` hoặc `policy_discrepancy` của case đó.
2. Cột `stage` trong `gate_fail` chỉ thẳng nơi cần sửa (`policy`, `payment`, `assemble`, …).
3. Sửa nguyên nhân trong `core.py` hoặc `pipeline.py`.
4. Chạy lại đúng case đó:

```bash
python run.py --case EC_007
```

Lệnh này **append** trace (không xoá 49 case kia) và ghi đè đúng một file output.

5. Chạy lại `--validate`.

Nếu sửa vào `core.py`, chạy lại `--unittest` và `--selftest` trước để chắc chắn không làm hỏng case khác.

---

## 6. Phương án dự phòng

| Tình huống | Lệnh |
|---|---|
| Provider LLM sập / rate-limit / hết quota | `python run.py --all --no-llm` |
| Muốn kiểm tra output đã có mà không chạy lại | `python run.py --validate` |
| Nghi ngờ dữ liệu vào sai | `python run.py --selftest` |

`--no-llm` vẫn sinh đủ 50 output đúng schema từ rule engine tất định. Mất phần điểm kiến trúc agent, **giữ được toàn bộ điểm nội dung**. Đây là van an toàn quan trọng nhất của hệ thống.

---

## 7. Checklist nộp bài

- [ ] `output/` có đúng 50 file, `--validate` in `SAN SANG NOP`
- [ ] `metadata.json` có `"run_type": "official"` và đúng model đã dùng
- [ ] `trace.jsonl` là của lượt chạy 50 case mới nhất
- [ ] `architecture.md` đã điền (sơ đồ agent, vai trò, quyền truy cập, luồng handoff)
- [ ] `individual_01352_NguyenCaoQuangAnh.md` đã điền
- [ ] `.env` **không** nằm trong git
- [ ] Source code đã commit và push
- [ ] `output.zip` chỉ chứa 50 JSON
