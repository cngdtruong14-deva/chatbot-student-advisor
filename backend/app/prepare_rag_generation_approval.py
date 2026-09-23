"""Create unsigned benchmark-generation or runtime-approval templates.

Templates never enable a provider.  The owner must review, complete and sign
them after the corresponding Dev/Final evidence exists.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.llm_runtime import prompt_sha256
from app.rag_benchmark_v2 import file_sha256, load_json_object, load_jsonl
from app.rag_generation_approval import approval_template
from app.rag_runtime import CAPSTONE_WAIVER_PROTOCOL


def generation_template(dataset: Path, split: str, binding_path: Path) -> dict:
    binding = load_json_object(binding_path, "RUNTIME_BINDING")
    binding.setdefault("prompt", {})
    if binding["prompt"].get("sha256") not in (None, prompt_sha256()):
        raise ValueError("RUNTIME_BINDING_PROMPT_IMPLEMENTATION_MISMATCH")
    binding["prompt"]["sha256"] = prompt_sha256()
    return approval_template(rows=load_jsonl(dataset), split=split, runtime_binding=binding)


def runtime_template(report_path: Path, *, semantic_review_path: Path | None = None, capstone_waiver: bool = False) -> dict:
    report = load_json_object(report_path, "FINAL_REPORT")
    if report.get("split") != "test" or len(report.get("results", [])) != 60:
        raise ValueError("RUNTIME_APPROVAL_REQUIRES_60_ROW_FINAL_TEST")
    quality = report.get("quality") or {}
    proxy = quality.get("thresholds_met_proxy") or {}
    standard_ready = bool(proxy and all(proxy.values()) and quality.get("infrastructure_error_count") == 0)
    semantic = None
    rejected_ids: list[str] = []
    if not standard_ready:
        if not capstone_waiver or semantic_review_path is None:
            raise ValueError("RUNTIME_APPROVAL_PROXY_GATES_NOT_MET")
        safety_keys = ("hit_at_5", "mrr_at_5", "safe_abstention", "citation_precision_proxy", "scope_leakage")
        if quality.get("infrastructure_error_count") != 0 or any(proxy.get(key) is not True for key in safety_keys):
            raise ValueError("CAPSTONE_WAIVER_SAFETY_GATES_NOT_MET")
        observed = quality.get("answer_correctness_proxy")
        if isinstance(observed, bool) or not isinstance(observed, (int, float)) or float(observed) < 0.875:
            raise ValueError("CAPSTONE_WAIVER_CORRECTNESS_BELOW_ACCEPTED_MINIMUM")
        semantic = load_json_object(semantic_review_path, "SEMANTIC_REVIEW")
        if semantic.get("final_report_sha256") != file_sha256(report_path) or semantic.get("answer_method") != report.get("answer_method"):
            raise ValueError("CAPSTONE_WAIVER_SEMANTIC_REVIEW_BINDING_MISMATCH")
        entries = semantic.get("entries")
        if not isinstance(entries, list) or len(entries) != 60:
            raise ValueError("CAPSTONE_WAIVER_REQUIRES_60_SEMANTIC_ROWS")
        rejected_ids = [str(item.get("question_id")) for item in entries if isinstance(item, dict) and item.get("approved") is not True]
        if len(rejected_ids) != 1 or semantic.get("approved_count") != 59:
            raise ValueError("CAPSTONE_WAIVER_REQUIRES_59_OF_60_SEMANTIC_APPROVALS")
        by_id = {str(item.get("question_id")): item for item in report["results"]}
        rejected = by_id.get(rejected_ids[0])
        actual = rejected.get("actual_response") if isinstance(rejected, dict) else None
        if not isinstance(actual, dict) or actual.get("status") != "insufficient_evidence" or actual.get("claims"):
            raise ValueError("CAPSTONE_WAIVER_REJECTED_ROW_MUST_BE_SAFE_ABSTENTION")
    binding = report.get("runtime_binding") or {}
    runtime_release = binding.get("runtime_release_context")
    required_release_keys = {"release_id", "chunks_hash", "receipt_sha256", "source_manifest_hash"}
    if not isinstance(runtime_release, dict) or not required_release_keys.issubset(runtime_release):
        raise ValueError("RUNTIME_RELEASE_CONTEXT_REQUIRED")
    value = {
        "protocol": "rag_runtime_quality_v2",
        "approved": False,
        "owner": "",
        "approved_at": "",
        "benchmark": {
            "split": "test",
            "final_report_sha256": file_sha256(report_path),
            "dataset_canonical_sha256": report.get("dataset_canonical_sha256"),
        },
        "release": runtime_release,
        "retriever": binding.get("retriever"),
        "generation": {
            "provider": (binding.get("provider") or {}).get("provider"),
            "model": (binding.get("provider") or {}).get("model"),
            "prompt_version": (binding.get("prompt") or {}).get("version"),
            "prompt_sha256": (binding.get("prompt") or {}).get("sha256"),
            "temperature": 0,
            "max_output_tokens": 1200,
        },
        "quality_gates": {
            "hit_at_5": proxy.get("hit_at_5"),
            "mrr_at_5": proxy.get("mrr_at_5"),
            "safe_abstention": proxy.get("safe_abstention"),
            "citation_precision": proxy.get("citation_precision_proxy"),
            "answer_correctness": proxy.get("answer_correctness_proxy"),
            "scope_leakage_zero": proxy.get("scope_leakage"),
        },
        "semantic_review": ({
            "approved": False,
            "owner": "",
            "reviewed_at": "",
            "entries": semantic["entries"],
            "source_review_sha256": file_sha256(semantic_review_path),
        } if semantic is not None else {
            "approved": False,
            "owner": "",
            "reviewed_at": "",
            "entries": [{"question_id": item.get("question_id"), "approved": False, "note": ""} for item in report["results"]],
        }),
        "approval_sha256": "SET_AFTER_OWNER_REVIEW",
    }
    # A waiver is meaningful only for a Final that missed the normal gate.
    # Refuse to attach one to an already-passing release because that would
    # make the operational status needlessly ambiguous.
    if capstone_waiver and standard_ready:
        raise ValueError("CAPSTONE_WAIVER_NOT_REQUIRED")
    if capstone_waiver:
        value["capstone_waiver"] = {
            "protocol": CAPSTONE_WAIVER_PROTOCOL,
            "approved": False,
            "owner": "",
            "reviewed_at": "",
            "scope": "capstone_demo_only",
            "final_report_sha256": file_sha256(report_path),
            "observed_answer_correctness_proxy": quality.get("answer_correctness_proxy"),
            "minimum_accepted_answer_correctness_proxy": 0.875,
            "semantic_approved_count": 59,
            "accepted_rejected_question_ids": rejected_ids,
            "accepted_risk": "One answerable benchmark row safely abstained; no hallucination, citation, scope or infrastructure failure is waived.",
            "risk_controls": {
                "citations_required": True,
                "fail_closed": True,
                "high_stakes_retrieval_only": True,
                "release_hash_bound": True,
            },
        }
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    generation = sub.add_parser("generation")
    generation.add_argument("--dataset", required=True)
    generation.add_argument("--split", choices=("dev", "test"), required=True)
    generation.add_argument("--runtime-binding", required=True)
    generation.add_argument("--output", required=True)
    runtime = sub.add_parser("runtime")
    runtime.add_argument("--final-report", required=True)
    runtime.add_argument("--semantic-review")
    runtime.add_argument("--capstone-waiver", action="store_true")
    runtime.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError("APPROVAL_TEMPLATE_OUTPUT_EXISTS")
    value = (generation_template(Path(args.dataset), args.split, Path(args.runtime_binding))
             if args.mode == "generation" else runtime_template(
                 Path(args.final_report),
                 semantic_review_path=Path(args.semantic_review) if args.semantic_review else None,
                 capstone_waiver=args.capstone_waiver,
             ))
    with output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": "OWNER_REVIEW_REQUIRED", "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
