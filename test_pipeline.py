"""Lightweight end-to-end checks for generated Olist dispute outputs.

Run after `python run_pipeline.py` (or `--dry-run`). It uses only the standard
library, so it is suitable for a quick pre-submission smoke test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from run_pipeline import Store, policy

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "input"
OUTPUT = ROOT / "output"
TRACE = ROOT / "logging" / "trace.jsonl"

REQUIRED_TOP_LEVEL = {
    "case_id", "case_assessment", "affected_entities", "customer_context",
    "product_context", "delivery_analysis", "payment_reconciliation",
    "root_cause_analysis", "evidence_ids", "financial_resolution", "resolution_actions",
}
ALLOWED_PRIMARY = {
    "canceled_order_paid", "unavailable_order_paid", "late_delivery_seller",
    "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    inputs = sorted(INPUT.glob("EC_*.json"))
    outputs = sorted(OUTPUT.glob("EC_*.json"))
    if len(inputs) != 50:
        fail(f"expected 50 inputs, found {len(inputs)}")
    if len(outputs) != 50:
        fail(f"expected 50 outputs, found {len(outputs)}")

    completed_cases: set[str] = set()
    store = Store()
    if not TRACE.exists():
        fail("missing logging/trace.jsonl")
    for line_number, raw in enumerate(TRACE.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as error:
            fail(f"trace line {line_number} is not valid JSON: {error}")
        if event.get("step") == "validation_completed" and event.get("status") == "passed":
            completed_cases.add(event.get("case_id", ""))

    for source in inputs:
        expected_case = json.loads(source.read_text(encoding="utf-8"))
        target = OUTPUT / source.name
        if not target.exists():
            fail(f"missing output for {source.name}")
        result = json.loads(target.read_text(encoding="utf-8"))
        canonical = policy(store.evidence(expected_case))
        missing = REQUIRED_TOP_LEVEL - result.keys()
        if missing:
            fail(f"{source.name}: missing keys {sorted(missing)}")
        if result["case_id"] != expected_case["case_id"]:
            fail(f"{source.name}: case_id mismatch")
        if result != canonical:
            fail(f"{source.name}: output is not the canonical evidence-based policy result")
        if result["case_assessment"]["primary_issue"] not in ALLOWED_PRIMARY:
            fail(f"{source.name}: unknown primary issue")
        claimed_order = expected_case["customer_request"]["claimed_order_id"]
        if result["affected_entities"]["order_ids"] != [claimed_order]:
            fail(f"{source.name}: affected order does not match claimed order")
        confidence = result["case_assessment"].get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            fail(f"{source.name}: confidence must be in [0, 1]")
        if len(result["evidence_ids"]) > 20 or len(result["resolution_actions"]) > 5:
            fail(f"{source.name}: output limits exceeded")
        parties = result["root_cause_analysis"]["responsible_parties"]
        if len(parties) > 3:
            fail(f"{source.name}: responsible-party limit exceeded")
        if result["case_assessment"]["primary_issue"] == "late_delivery_seller":
            expected_sellers = result["delivery_analysis"]["late_handoff_seller_ids"]
            if [party["party_id"] for party in parties] != expected_sellers:
                fail(f"{source.name}: missing or incorrect late-handoff seller responsibility")
        if result["case_id"] not in completed_cases:
            fail(f"{source.name}: no successful validation event in trace")

    print(f"PASS: {len(inputs)} inputs -> {len(outputs)} outputs; {len(completed_cases)} cases validated in trace.")


if __name__ == "__main__":
    main()
