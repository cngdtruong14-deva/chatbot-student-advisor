"""Freeze a fully reviewed V4 dataset and its line-by-line ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from app.prepare_rag_benchmark_v4 import prepare
from app.rag_benchmark_v2 import load_jsonl, validate_benchmark_protocol


CONFIRM = "OWNER_REVIEWED_ALL_120_V4_ROWS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--prior", action="append", required=True)
    parser.add_argument("--dataset-output", type=Path, required=True)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRM:
        raise ValueError("V4_EXPLICIT_OWNER_REVIEW_CONFIRMATION_REQUIRED")
    if args.dataset_output.exists() or args.ledger_output.exists():
        raise ValueError("V4_SIGNED_OUTPUT_EXISTS")
    rows = load_jsonl(args.input)
    prior_rows = [row for path in args.prior for row in load_jsonl(path)]
    prepare([dict(row) for row in rows], prior_rows)
    owner = args.owner.strip()
    if not owner:
        raise ValueError("V4_OWNER_REQUIRED")
    for row in rows:
        if row.get("reviewed") is not True or str(row.get("reviewer") or "").strip() != owner or not row.get("reviewed_at"):
            raise ValueError(f"V4_ROW_NOT_OWNER_REVIEWED:{row.get('question_id')}")
    protocol = validate_benchmark_protocol(rows)
    reviewed_at = datetime.now(timezone.utc).isoformat()
    ledger = {
        "protocol": protocol["protocol"],
        "benchmark_version": "V4",
        "approved": True,
        "owner": owner,
        "reviewed_at": reviewed_at,
        "dataset_canonical_sha256": protocol["dataset_canonical_sha256"],
        "split_canonical_sha256": protocol["split_canonical_sha256"],
        "methodology_notice": {
            "verification_label": "Single-Reviewer Verified",
            "inter_annotator_agreement": "Not available for this single-owner capstone review",
        },
        "entries": [{
            "question_id": row["question_id"],
            "reviewed": True,
            "reviewer": row["reviewer"],
            "reviewed_at": row["reviewed_at"],
            "category": row["benchmark_category"],
            "split": row["split"],
            "group_id": row["group_id"],
        } for row in rows],
    }
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    with args.dataset_output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    args.ledger_output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OWNER_REVIEW_FROZEN", "benchmark_version": "V4", "question_count": 120,
                      "dataset_canonical_sha256": protocol["dataset_canonical_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
