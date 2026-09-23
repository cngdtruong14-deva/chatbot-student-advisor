"""Sign a completed Stage-7 approval without making review decisions.

The owner must inspect and complete the input template first.  This command
only stamps identity/time and computes the canonical approval hash after an
explicit, kind-specific confirmation phrase.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from app.rag_benchmark_v2 import V3_FREEZE_VERSION, V4_FREEZE_VERSION, canonical_sha256
from app.rag_generation_approval import PROTOCOL as GENERATION_PROTOCOL
from app.rag_runtime import CAPSTONE_WAIVER_PROTOCOL


CONFIRM = {
    "generation": "OWNER_APPROVED_ISOLATED_GEMINI_BENCHMARK",
    "freeze": "OWNER_FROZE_V3_AFTER_DEV",
    "runtime": "OWNER_APPROVED_60_OF_60_FINAL_RESPONSES",
}
CAPSTONE_RUNTIME_CONFIRM = "OWNER_ACCEPTED_CAPSTONE_V4_WAIVER"
FREEZE_CONFIRM = {
    V3_FREEZE_VERSION: "OWNER_FROZE_V3_AFTER_DEV",
    V4_FREEZE_VERSION: "OWNER_FROZE_V4_AFTER_DEV",
}


def _hash(value: dict) -> str:
    return canonical_sha256({key: item for key, item in value.items() if key != "approval_sha256"})


def _validate_generation(value: dict) -> None:
    if value.get("protocol") != GENERATION_PROTOCOL or value.get("usage_scope") != "isolated_benchmark_only":
        raise ValueError("STAGE7_GENERATION_TEMPLATE_INVALID")
    if value.get("split") not in {"dev", "test"}:
        raise ValueError("STAGE7_GENERATION_SPLIT_INVALID")


def _validate_freeze(value: dict) -> None:
    if value.get("freeze_version") not in FREEZE_CONFIRM or value.get("final_split") != "test":
        raise ValueError("STAGE7_FREEZE_TEMPLATE_INVALID")
    if not value.get("dev_evidence", {}).get("report_sha256"):
        raise ValueError("STAGE7_FREEZE_DEV_EVIDENCE_REQUIRED")


def _validate_runtime(value: dict) -> None:
    if value.get("protocol") != "rag_runtime_quality_v2":
        raise ValueError("STAGE7_RUNTIME_TEMPLATE_INVALID")
    review = value.get("semantic_review")
    entries = review.get("entries") if isinstance(review, dict) else None
    if not isinstance(entries, list) or len(entries) != 60:
        raise ValueError("STAGE7_RUNTIME_REQUIRES_60_RESPONSES")
    rejected = [item for item in entries if not isinstance(item, dict) or item.get("approved") is not True]
    waiver = value.get("capstone_waiver")
    if not rejected:
        return
    if not isinstance(waiver, dict) or waiver.get("protocol") != CAPSTONE_WAIVER_PROTOCOL:
        raise ValueError("STAGE7_RUNTIME_ALL_60_RESPONSES_MUST_BE_APPROVED")
    if len(rejected) != 1 or waiver.get("scope") != "capstone_demo_only" or waiver.get("approved") is not False:
        raise ValueError("STAGE7_CAPSTONE_WAIVER_INVALID")
    if waiver.get("accepted_rejected_question_ids") != [rejected[0].get("question_id")]:
        raise ValueError("STAGE7_CAPSTONE_WAIVER_REJECTED_ROW_MISMATCH")
    controls = waiver.get("risk_controls") or {}
    if any(controls.get(name) is not True for name in (
        "citations_required", "fail_closed", "high_stakes_retrieval_only", "release_hash_bound",
    )):
        raise ValueError("STAGE7_CAPSTONE_WAIVER_SAFETY_CONTROLS_REQUIRED")
    gates = value.get("quality_gates") or {}
    safety_gates = ("hit_at_5", "mrr_at_5", "safe_abstention", "citation_precision", "scope_leakage_zero")
    if gates.get("answer_correctness") is not False or any(gates.get(name) is not True for name in safety_gates):
        raise ValueError("STAGE7_CAPSTONE_WAIVER_QUALITY_GATES_INVALID")
    if waiver.get("observed_answer_correctness_proxy") != 0.875 or waiver.get("minimum_accepted_answer_correctness_proxy") != 0.875:
        raise ValueError("STAGE7_CAPSTONE_WAIVER_THRESHOLD_INVALID")
    if waiver.get("final_report_sha256") != (value.get("benchmark") or {}).get("final_report_sha256"):
        raise ValueError("STAGE7_CAPSTONE_WAIVER_REPORT_BINDING_INVALID")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=tuple(CONFIRM), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    unsigned = json.loads(args.input.read_text(encoding="utf-8"))
    expected_confirm = (
        FREEZE_CONFIRM.get(unsigned.get("freeze_version")) if args.kind == "freeze"
        else CAPSTONE_RUNTIME_CONFIRM if args.kind == "runtime" and unsigned.get("capstone_waiver")
        else CONFIRM[args.kind]
    )
    if args.confirm != expected_confirm:
        raise ValueError("STAGE7_EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    if args.output.exists():
        raise ValueError("STAGE7_SIGNED_APPROVAL_OUTPUT_EXISTS")
    value = unsigned
    if not isinstance(value, dict):
        raise ValueError("STAGE7_APPROVAL_NOT_OBJECT")
    {"generation": _validate_generation, "freeze": _validate_freeze, "runtime": _validate_runtime}[args.kind](value)
    now = datetime.now(timezone.utc).isoformat()
    value["approved"] = True
    value["owner"] = args.owner.strip()
    if not value["owner"]:
        raise ValueError("STAGE7_OWNER_REQUIRED")
    if args.kind == "generation":
        value["approved_at"] = now
    elif args.kind == "freeze":
        value["approved_at"] = now
    else:
        value["approved_at"] = now
        if value.get("capstone_waiver"):
            value["semantic_review"].update(approved=False, owner=value["owner"], reviewed_at=now,
                                            state="accepted_under_capstone_waiver")
            value["capstone_waiver"].update(approved=True, owner=value["owner"], reviewed_at=now)
        else:
            value["semantic_review"].update(approved=True, owner=value["owner"], reviewed_at=now)
    value["approval_sha256"] = _hash(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OWNER_SIGNED", "kind": args.kind, "approval_sha256": value["approval_sha256"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
