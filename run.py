"""
run.py — CLI cua he thong multi-agent K4 Day 09.

    python run.py --all                 # chay 50 case trong input/, ghi moi trace
    python run.py --case EC_007         # chay lai 1 case, append trace
    python run.py --selftest            # sinh case tu CSV that, chay end-to-end
    python run.py --unittest            # 3 phep tinh lay tu vi du README §6
    python run.py --all --no-llm        # chi loi tat dinh, bo moi LLM call
    python run.py --validate            # kiem tra lai output/ da co
    python run.py --zip                 # dong goi output/ thanh submission.zip
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import core
from core import DataStore, Verifier, hours_between
from pipeline import (
    ACTIVE_PROFILE,
    CaseInput,
    CaseRunner,
    LLMClient,
    Tracer,
    active_models,
    required_env_keys,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
LOG_DIR = ROOT / "logging"
SELFTEST_DIR = ROOT / "selftest"


# ---------------------------------------------------------------------------
# .env loader toi gian (khong them phu thuoc)
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------------------------------------------------------------------------
# Doc / ghi case
# ---------------------------------------------------------------------------

def read_cases(directory: Path) -> list[CaseInput]:
    files = sorted(directory.glob("EC_*.json"))
    cases = []
    for f in files:
        try:
            cases.append(CaseInput.from_json(json.loads(f.read_text(encoding="utf-8"))))
        except Exception as exc:  # noqa: BLE001
            print(f"  [LOI] khong doc duoc {f.name}: {exc}", file=sys.stderr)
    return cases


def write_output(out: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{out['case_id']}.json"
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# metadata.json
# ---------------------------------------------------------------------------

def write_metadata(started: float, finished: float, cases: int,
                   tracer: Tracer, llm_enabled: bool) -> Path:
    import platform

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / "metadata.json"
    models = [{"agent": agent, **spec} for agent, spec in active_models().items()]
    # Nhan trung thuc: chi lot chay tren input/ that moi la 'official'. Lot chay
    # tren input mo phong duoc danh dau ro de khong bi nham la bai nop.
    official = INPUT_DIR == ROOT / "input"
    payload = {
        "run_type": "official" if official else "simulation",
        "input_dir": str(INPUT_DIR),
        "profile": ACTIVE_PROFILE,
        "models": models,
        "model_constraint": "moi agent dung model <= 10B tham so (README §9.1)",
        "llm_enabled": llm_enabled,
        "framework": "custom multi-agent orchestration (OpenAI-compatible client)",
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pandas": __import__("pandas").__version__,
        },
        "run": {
            "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
            "finished_at": datetime.fromtimestamp(finished, timezone.utc).isoformat(),
            "duration_seconds": round(finished - started, 2),
            "cases": cases,
            **tracer.counters,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Self-test: sinh case tu du lieu that
# ---------------------------------------------------------------------------

SELFTEST_SPECS: list[tuple[str, str]] = [
    ("canceled_order_paid", "order_status=canceled va co payment"),
    ("unavailable_order_paid", "order_status=unavailable va co payment"),
    ("late_delivery_seller", "giao tre va co seller ban giao tre"),
    ("late_delivery_logistics", "giao tre nhung khong seller nao tre"),
    ("valid_split_payment", ">=2 payment row va doi soat khop"),
    ("unsupported_late_claim", "giao dung han, payment khop"),
    ("no_item_rows", "order khong co item row -> null handling"),
    ("no_delivery_date", "chua tung giao -> delivery_variance null"),
    ("many_items", ">5 item -> truncation"),
    ("many_payments", ">5 payment -> truncation"),
    ("many_sellers", ">3 seller -> truncation"),
    ("no_payment_rows", "order khong co payment row"),
]


def build_selftest_cases(store: DataStore) -> list[tuple[str, str, str]]:
    """Tra ve [(label, order_id, mo_ta)] — quet CSV tim order THAT cho tung nhanh."""
    engine = core.PolicyEngine()
    picks: dict[str, str] = {}

    for order_id, order in store.orders.items():
        items = store.items(order_id)
        pays = store.payments(order_id)

        if "no_item_rows" not in picks and not items and pays:
            picks["no_item_rows"] = order_id
        if "no_payment_rows" not in picks and not pays:
            picks["no_payment_rows"] = order_id
        if "many_items" not in picks and len(items) > 5:
            picks["many_items"] = order_id
        if "many_payments" not in picks and len(pays) > 5:
            picks["many_payments"] = order_id
        if "many_sellers" not in picks and len({i.seller_id for i in items}) > 3:
            picks["many_sellers"] = order_id
        if ("no_delivery_date" not in picks
                and order.delivered_customer.dt is None and items and pays):
            picks["no_delivery_date"] = order_id

        needed = {label for label, _ in SELFTEST_SPECS[:6]} - set(picks)
        if needed:
            bundle = core.EvidenceBundle(
                case_id="PROBE", order_id=order_id, order_exists=True,
                customer=core.CustomerTools(store).resolve(order_id, True),
                order_product=core.OrderProductTools(store).inspect(order_id, True),
                payment=core.PaymentTools(store).reconcile(order_id),
                delivery=core.DeliveryTools(store).analyse(order_id),
            )
            primary = engine.decide(bundle).primary_issue
            if primary in needed:
                picks[primary] = order_id

        if len(picks) == len(SELFTEST_SPECS):
            break

    desc = dict(SELFTEST_SPECS)
    return [(label, picks[label], desc[label])
            for label, _ in SELFTEST_SPECS if label in picks]


def cmd_selftest(store: DataStore, llm_enabled: bool) -> int:
    print("\n=== SELF-TEST: sinh case tu du lieu that ===\n")
    specs = build_selftest_cases(store)

    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    in_dir = SELFTEST_DIR / "input"
    out_dir = SELFTEST_DIR / "output"
    in_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)

    cases: list[CaseInput] = []
    for i, (label, order_id, _) in enumerate(specs, start=1):
        payload = {
            "case_id": f"EC_{i:03d}",
            "customer_request": {
                "language": "vi",
                "message": f"[selftest:{label}] Hay dieu tra khieu nai nay.",
                "claimed_order_id": order_id,
            },
            "investigation_scope": {
                "include_customer_history": True,
                "include_product_context": True,
            },
            "policy_version": "EC_POLICY_V2",
        }
        (in_dir / f"EC_{i:03d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        cases.append(CaseInput.from_json(payload))

    tracer = Tracer(SELFTEST_DIR / "trace.jsonl", mode="w")
    llm = LLMClient(enabled=llm_enabled, tracer=tracer)
    runner = CaseRunner(store, tracer, llm)
    verifier = Verifier(store)

    print(f"{'case':<8} {'nhanh mong doi':<24} {'primary_issue thuc te':<24} "
          f"{'gate':<6} refund")
    print("-" * 86)

    all_pass = True
    for case, (label, order_id, _note) in zip(cases, specs):
        out = runner.run(case)
        write_output(out, out_dir)
        failures = verifier.run(out)
        primary = out["case_assessment"]["primary_issue"]
        refund = out["financial_resolution"]["recommended_refund_brl"]

        expected_branch = label in dict(SELFTEST_SPECS[:6])
        branch_ok = (not expected_branch) or (primary == label)
        gate_ok = not failures
        ok = branch_ok and gate_ok
        all_pass = all_pass and ok

        mark = "OK  " if ok else "FAIL"
        print(f"{case.case_id:<8} {label:<24} {primary:<24} {mark:<6} {refund}")
        for f in failures:
            print(f"         └─ [{f.code}] {f.message}")

    tracer.close()
    print("-" * 86)
    print(f"\nKet qua: {'TAT CA PASS' if all_pass else 'CO CASE FAIL'}")
    print(f"Input mo phong : {in_dir}")
    print(f"Output         : {out_dir}")
    print(f"Trace          : {SELFTEST_DIR / 'trace.jsonl'}")
    return 0 if all_pass else 1


# ---------------------------------------------------------------------------
# Unit test tu vi du README §6 — ground truth duy nhat co san
# ---------------------------------------------------------------------------

def cmd_unittest() -> int:
    print("\n=== UNIT TEST: 3 phep tinh lay tu vi du README §6 ===\n")
    fmt = "%Y-%m-%d %H:%M:%S"
    checks = [
        (
            "delivery_variance_hours",
            hours_between(datetime.strptime("2018-03-31 15:23:33", fmt),
                          datetime.strptime("2018-03-28 00:00:00", fmt)),
            87.39,
        ),
        (
            "handoff_variance_hours",
            hours_between(datetime.strptime("2018-03-15 21:33:51", fmt),
                          datetime.strptime("2018-03-15 20:31:15", fmt)),
            1.04,
        ),
        (
            "refund = tong freight",
            core.money(Decimal("18.27")),
            18.27,
        ),
        (
            "expected_total = item + freight",
            core.money(Decimal("194.00") + Decimal("18.27")),
            212.27,
        ),
        (
            "difference = payment - expected",
            core.money(Decimal("212.27") - (Decimal("194.00") + Decimal("18.27"))),
            0.0,
        ),
    ]
    ok = True
    for label, got, want in checks:
        good = got == want
        ok = ok and good
        print(f"  {'OK  ' if good else 'FAIL'}  {label:<34} got={got!r:<10} want={want!r}")
    print(f"\nKet qua: {'TAT CA PASS' if ok else 'CO PHEP TINH SAI'}")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Chay that
# ---------------------------------------------------------------------------

def cmd_run(store: DataStore, cases: list[CaseInput], llm_enabled: bool,
            trace_mode: str, workers: int = 1, variant: Any = None) -> int:
    if not cases:
        print(f"\n[!] Khong tim thay file EC_*.json nao trong {INPUT_DIR}")
        print("    Input duoc cong bo o Checkpoint 1. Dung --selftest de "
              "kiem chung truoc.")
        return 1

    started = time.time()
    tracer = Tracer(LOG_DIR / "trace.jsonl", mode=trace_mode)
    llm = LLMClient(enabled=llm_enabled, tracer=tracer)
    runner = CaseRunner(store, tracer, llm, variant)

    if llm_enabled and not llm.enabled:
        print(f"[!] Khong khoi tao duoc LLM. Profile '{ACTIVE_PROFILE}' can: "
              f"{', '.join(required_env_keys())}. Thieu: "
              f"{', '.join(llm.missing_keys) or 'khong ro'}.")
        print("    -> Chay o che do tat dinh (tuong duong --no-llm).")
    elif llm_enabled and llm.missing_keys:
        print(f"[!] Thieu mot phan key: {', '.join(llm.missing_keys)}. "
              f"Cac agent thuoc provider do se chay o che do tat dinh.")

    # Chi song song khi that su goi LLM. O che do tat dinh, 50 case chay het
    # 0,1 giay nen them thread chi lam phuc tap them.
    effective_workers = workers if (llm.enabled and workers > 1) else 1

    print(f"\nChay {len(cases)} case | profile={ACTIVE_PROFILE} | "
          f"LLM={'bat' if llm.enabled else 'tat'} | workers={effective_workers}\n")

    counts: dict[str, int] = {}
    done = 0

    def process(case: CaseInput) -> tuple[CaseInput, dict[str, Any]]:
        return case, runner.run(case)

    def record(case: CaseInput, out: dict[str, Any]) -> None:
        nonlocal done
        write_output(out, OUTPUT_DIR)
        primary = out["case_assessment"]["primary_issue"]
        counts[primary] = counts.get(primary, 0) + 1
        done += 1
        print(f"  [{done:>2}/{len(cases)}] {case.case_id}  {primary:<24} "
              f"refund={out['financial_resolution']['recommended_refund_brl']}")

    if effective_workers > 1:
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            for case, out in pool.map(process, cases):
                record(case, out)
    else:
        for case in cases:
            record(*process(case))

    finished = time.time()
    meta = write_metadata(started, finished, len(cases), tracer, llm.enabled)
    tracer.close()

    print(f"\n--- Phan bo primary_issue ---")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<26} {v}")
    print(f"\nOutput   : {OUTPUT_DIR}  ({len(list(OUTPUT_DIR.glob('EC_*.json')))} file)")
    print(f"Trace    : {LOG_DIR / 'trace.jsonl'}")
    print(f"Metadata : {meta}")
    print(f"Thoi gian: {finished - started:.1f}s")
    return 0


# ---------------------------------------------------------------------------
# Validate + zip
# ---------------------------------------------------------------------------

def cmd_validate(store: DataStore, expect: int = 50) -> int:
    print(f"\n=== VALIDATE {OUTPUT_DIR} ===\n")
    files = sorted(OUTPUT_DIR.glob("EC_*.json"))
    verifier = Verifier(store)
    total_fail = 0

    for f in files:
        # Bat truong hop file bi mot cong cu BEN NGOAI ghi de (tung xay ra:
        # mot trinh format JSON thay het null -> "N/A"/0.0/false va them BOM).
        raw = f.read_bytes()
        encoding_issue = None
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding_issue = "file co BOM UTF-8 (pipeline khong bao gio ghi BOM)"
        elif b'"N/A"' in raw:
            encoding_issue = 'file chua chuoi "N/A" (pipeline khong bao gio sinh ra)'
        if encoding_issue:
            print(f"  [FAIL] {f.name}: {encoding_issue}")
            print("         -> file da bi sua ngoai pipeline. Khoi phuc bang:")
            print("            git checkout -- output/    hoac    python run.py --all")
            total_fail += 1
            continue
        try:
            out = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {f.name}: khong parse duoc JSON ({exc})")
            total_fail += 1
            continue
        failures = verifier.run(out)
        if failures:
            total_fail += 1
            print(f"  [FAIL] {f.name}")
            for x in failures:
                print(f"         └─ [{x.code}] {x.message}")

    stray = [p.name for p in OUTPUT_DIR.iterdir()
             if p.is_file() and not p.name.startswith("EC_")
             and p.name != ".gitkeep"]

    print(f"\n  So file EC_*.json : {len(files)} (can {expect})")
    print(f"  File la trong output/: {stray or 'khong co'}")
    print(f"  File fail gate    : {total_fail}")
    ok = len(files) == expect and total_fail == 0 and not stray
    print(f"\nKet qua: {'SAN SANG NOP' if ok else 'CHUA DAT'}")
    return 0 if ok else 1


def cmd_zip(src: Path | None = None, target: Path | None = None) -> int:
    src = src or OUTPUT_DIR
    target = target or (ROOT / "submission.zip")
    files = sorted(src.glob("EC_*.json"))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)   # phang, khong kem thu muc
    print(f"  Da dong goi {len(files)} file -> {target.name}")
    return 0


def cmd_all_variants(cases: list[CaseInput]) -> int:
    """Sinh moi variant de nop thu va so diem.

    Moi variant doi DUNG MOT gia dinh so voi 'base'. Chay o che do tat dinh:
    LLM khong anh huong den bat ky gia tri nao trong output nen khong can goi.
    """
    root = ROOT / "variants"
    root.mkdir(exist_ok=True)
    base_out: dict[str, dict[str, Any]] = {}
    summary = []

    for name, variant in core.VARIANTS.items():
        # 'cat_en' doi du lieu goc -> phai nap lai DataStore.
        store = DataStore(DATA_DIR, english_categories=variant.english_categories).load()
        out_dir = root / name
        out_dir.mkdir(exist_ok=True)
        tracer = Tracer(root / f"trace_{name}.jsonl", mode="w")
        runner = CaseRunner(store, tracer, LLMClient(enabled=False), variant)

        outs = {}
        for case in cases:
            out = runner.run(case)
            outs[case.case_id] = out
            write_output(out, out_dir)
        tracer.close()

        if name == "base":
            base_out = outs
            changed = 0
        else:
            changed = sum(1 for k in outs if outs[k] != base_out.get(k))

        failures = sum(1 for o in outs.values() if Verifier(store).run(o))
        cmd_zip(out_dir, root / f"submission_{name}.zip")
        summary.append((name, changed, failures))
        print(f"  variant '{name}': {changed} case khac base, {failures} case fail gate\n")

    print("\n=== TOM TAT ===")
    print(f"{'variant':<16} {'case khac base':<16} {'fail gate'}")
    for name, changed, failures in summary:
        print(f"{name:<16} {changed:<16} {failures}")
    print(f"\nZip nam trong: {root}")
    print("Nop tung file submission_<ten>.zip roi so diem de biet cach doc nao dung.")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="K4 Day 09 multi-agent pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="chay toan bo input/")
    group.add_argument("--case", metavar="EC_007", help="chay lai mot case")
    group.add_argument("--selftest", action="store_true",
                       help="sinh case tu CSV that va chay end-to-end")
    group.add_argument("--unittest", action="store_true",
                       help="kiem tra 3 phep tinh trong vi du README")
    group.add_argument("--validate", action="store_true",
                       help="kiem tra lai output/ da co")
    group.add_argument("--zip", action="store_true", help="dong goi submission.zip")
    group.add_argument("--all-variants", action="store_true",
                       help="sinh MOI variant vao variants/<ten>/ + zip rieng")
    parser.add_argument("--no-llm", action="store_true",
                        help="chi chay loi tat dinh, bo moi LLM call")
    parser.add_argument("--expect", type=int, default=50,
                        help="so file mong doi khi --validate")
    parser.add_argument("--input-dir", help="ghi de input/ (dung de chay thu)")
    parser.add_argument("--output-dir", help="ghi de output/ (dung de chay thu)")
    parser.add_argument("--workers", type=int, default=6,
                        help="so case chay song song khi bat LLM (mac dinh 6)")
    parser.add_argument("--variant", default="base",
                        choices=sorted(core.VARIANTS),
                        help="cach doc cac diem de bai khong dac ta ro")
    args = parser.parse_args()

    global INPUT_DIR, OUTPUT_DIR
    if args.input_dir:
        INPUT_DIR = Path(args.input_dir)
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)

    load_dotenv(ROOT / ".env")

    if args.unittest:
        return cmd_unittest()

    if args.zip:
        return cmd_zip()

    variant = core.VARIANTS[args.variant]

    if args.all_variants:
        cases = read_cases(INPUT_DIR)
        if not cases:
            print(f"[!] Khong co case nao trong {INPUT_DIR}")
            return 1
        print(f"\n=== SINH {len(core.VARIANTS)} VARIANT tren {len(cases)} case ===\n")
        return cmd_all_variants(cases)

    print("Dang nap du lieu Olist ...", end=" ", flush=True)
    t0 = time.time()
    store = DataStore(DATA_DIR,
                      english_categories=variant.english_categories).load()
    print(f"xong ({time.time() - t0:.1f}s) — "
          f"{len(store.orders):,} order, {len(store.items_by_order):,} order co item")

    llm_enabled = not args.no_llm

    if args.selftest:
        return cmd_selftest(store, llm_enabled)
    if args.validate:
        return cmd_validate(store, args.expect)
    if args.case:
        cases = [c for c in read_cases(INPUT_DIR) if c.case_id == args.case]
        if not cases:
            print(f"[!] Khong tim thay {args.case} trong {INPUT_DIR}")
            return 1
        return cmd_run(store, cases, llm_enabled, trace_mode="a",
                       workers=args.workers, variant=variant)
    return cmd_run(store, read_cases(INPUT_DIR), llm_enabled, trace_mode="w",
                   workers=args.workers, variant=variant)


if __name__ == "__main__":
    raise SystemExit(main())
