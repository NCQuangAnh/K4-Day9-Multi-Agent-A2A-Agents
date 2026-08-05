"""
main.py - Main pipeline for processing 50 e-commerce dispute resolution cases.
Reads from input/, processes via multi-agent system, writes to output/.
"""

import json
import os
import time
import sys

from dotenv import load_dotenv

load_dotenv()

from data_loader import OlistData
from agent_base import get_trace_entries, clear_trace_entries
from agents.coordinator_agent import CoordinatorAgent


# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGGING_DIR = os.path.join(BASE_DIR, "logging")


def main():
    print("=" * 60)
    print("Multi-Agent E-commerce Dispute Resolution System")
    print(f"Model: llama-3.1-8b-instant (8B params) via Groq API")
    print("=" * 60)

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOGGING_DIR, exist_ok=True)

    # Load data
    db = OlistData()

    # Initialize coordinator
    coordinator = CoordinatorAgent(db)

    # Find all input cases
    input_files = sorted([
        f for f in os.listdir(INPUT_DIR)
        if f.startswith("EC_") and f.endswith(".json")
    ])

    if not input_files:
        print("\n[WARNING] No input cases found in input/ directory.")
        print("Please add EC_001.json through EC_050.json to the input/ folder.")
        return

    print(f"\nFound {len(input_files)} input cases.")
    print("-" * 60)

    # Clear trace for fresh run
    clear_trace_entries()

    # Process each case
    success_count = 0
    error_count = 0
    start_time = time.time()

    for i, filename in enumerate(input_files):
        case_start = time.time()
        print(f"\n[{i + 1}/{len(input_files)}] Processing {filename}...")

        try:
            # Read input
            with open(os.path.join(INPUT_DIR, filename), "r", encoding="utf-8") as f:
                case_input = json.load(f)

            # Process case
            output = coordinator.process_case(case_input)

            # Write output (same filename)
            output_path = os.path.join(OUTPUT_DIR, filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            elapsed = time.time() - case_start
            print(f"  [OK] {filename} completed in {elapsed:.1f}s "
                  f"(primary: {output['case_assessment']['primary_issue']}, "
                  f"status: {output['case_assessment']['case_status']})")
            success_count += 1

        except Exception as e:
            elapsed = time.time() - case_start
            print(f"  [FAIL] {filename} failed in {elapsed:.1f}s: {e}")
            error_count += 1

            # Log the error in trace
            trace_entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "agent": "MainPipeline",
                "case_id": filename.replace(".json", ""),
                "action": "case_error",
                "error": str(e),
                "status": "error",
            }
            get_trace_entries().append(trace_entry)

    # Write trace
    trace_path = os.path.join(LOGGING_DIR, "trace.jsonl")
    with open(trace_path, "w", encoding="utf-8") as f:
        for entry in get_trace_entries():
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    total_time = time.time() - start_time

    print("\n" + "=" * 60)
    print(f"COMPLETE: {success_count} succeeded, {error_count} failed")
    print(f"Total time: {total_time:.1f}s")
    print(f"Trace written to: {trace_path}")
    print(f"Outputs written to: {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
