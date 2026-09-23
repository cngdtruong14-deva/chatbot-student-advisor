"""Create an unsigned one-shot Test freeze from reviewed V3/Dev evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.rag_benchmark_v2 import (
    V3_FREEZE_VERSION,
    canonical_sha256,
    file_sha256,
    load_json_object,
    load_jsonl,
    validate_benchmark_protocol,
    validate_review_ledger,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--review-ledger", type=Path, required=True)
    parser.add_argument("--runtime-binding", type=Path, required=True)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--dev-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("V3_FREEZE_TEMPLATE_OUTPUT_EXISTS")
    rows = load_jsonl(args.dataset)
    protocol = validate_benchmark_protocol(rows)
    ledger = load_json_object(args.review_ledger, "REVIEW_LEDGER")
    verified_ledger = validate_review_ledger(ledger, rows, protocol["dataset_canonical_sha256"])
    binding = load_json_object(args.runtime_binding, "RUNTIME_BINDING")
    report = load_json_object(args.dev_report, "DEV_REPORT")
    if report.get("split") != "dev" or report.get("dataset_canonical_sha256") != protocol["dataset_canonical_sha256"]:
        raise ValueError("V3_FREEZE_DEV_REPORT_DATASET_MISMATCH")
    selection = report.get("dev_selection") or {}
    selected = selection.get("recommended_method")
    if not selected or selected != (binding.get("retriever") or {}).get("method"):
        raise ValueError("V3_FREEZE_DEV_RETRIEVER_NOT_SELECTED")
    quality = report.get("quality") or {}
    if quality.get("infrastructure_error_count") != 0:
        raise ValueError("V3_FREEZE_DEV_INFRASTRUCTURE_ERRORS")
    release = binding.get("release")
    if not isinstance(release, dict):
        raise ValueError("V3_FREEZE_RELEASE_BINDING_REQUIRED")
    if release != {
        "release_id": binding.get("release_id"),
        "receipt_sha256": file_sha256(args.release_receipt),
        "manifest_sha256": file_sha256(args.release_manifest),
    }:
        raise ValueError("V3_FREEZE_RELEASE_BINDING_MISMATCH")
    value = {
        "freeze_version": V3_FREEZE_VERSION,
        "approved": False,
        "owner": "",
        "approved_at": "",
        "dataset": {
            "canonical_sha256": protocol["dataset_canonical_sha256"],
            "split_canonical_sha256": protocol["split_canonical_sha256"],
        },
        "final_split": "test",
        "review_ledger": {"canonical_sha256": verified_ledger["ledger_canonical_sha256"]},
        "release": release,
        "retriever": binding.get("retriever"),
        "prompt": binding.get("prompt"),
        "provider": binding.get("provider"),
        "source_provenance": binding.get("source_provenance"),
        "execution": binding.get("execution"),
        "dev_evidence": {
            "report_sha256": file_sha256(args.dev_report),
            "selected_method": selected,
            "quality": quality,
        },
        "approval_sha256": "SET_AFTER_OWNER_REVIEW",
    }
    value["template_sha256"] = canonical_sha256(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OWNER_FREEZE_APPROVAL_REQUIRED", "template_sha256": value["template_sha256"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
