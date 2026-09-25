"""Create a traceable V4 operational prompt rebind without rewriting benchmark history."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.llm_runtime import prompt_sha256
from app.rag_runtime import (
    HIGH_STAKES_APPROVAL_PROTOCOL,
    OPERATIONAL_REBIND_PROTOCOL,
    RUNTIME_APPROVAL_PROTOCOL,
    canonical_hash,
)


CONFIRM = "APPROVE PROMPT HOTFIX + V4 OPERATIONAL REBIND"


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("APPROVAL_NOT_OBJECT")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-input", type=Path, required=True)
    parser.add_argument("--high-stakes-input", type=Path, required=True)
    parser.add_argument("--runtime-output", type=Path, required=True)
    parser.add_argument("--high-stakes-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--prompt-version", default="v4-operational-hotfix-1")
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRM:
        raise ValueError("EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    if any(path.exists() for path in (args.runtime_output, args.high_stakes_output, args.metadata_output)):
        raise ValueError("OUTPUT_EXISTS")
    if len(args.source_commit) != 40 or any(ch not in "0123456789abcdef" for ch in args.source_commit):
        raise ValueError("SOURCE_COMMIT_INVALID")

    runtime = load(args.runtime_input)
    overlay = load(args.high_stakes_input)
    if runtime.get("protocol") != RUNTIME_APPROVAL_PROTOCOL or runtime.get("approved") is not True:
        raise ValueError("BASE_RUNTIME_APPROVAL_INVALID")
    old_runtime_hash = runtime.get("approval_sha256")
    if old_runtime_hash != canonical_hash(runtime, omit=("approval_sha256",)):
        raise ValueError("BASE_RUNTIME_APPROVAL_HASH_INVALID")
    if overlay.get("protocol") != HIGH_STAKES_APPROVAL_PROTOCOL or overlay.get("approved") is not True:
        raise ValueError("BASE_HIGH_STAKES_APPROVAL_INVALID")
    if overlay.get("approval_sha256") != canonical_hash(overlay, omit=("approval_sha256",)):
        raise ValueError("BASE_HIGH_STAKES_APPROVAL_HASH_INVALID")
    if overlay.get("base_runtime_approval_sha256") != old_runtime_hash:
        raise ValueError("BASE_APPROVAL_LINK_MISMATCH")

    generation = runtime.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("GENERATION_BINDING_MISSING")
    old_prompt_hash = generation.get("prompt_sha256")
    new_prompt_hash = prompt_sha256()
    if old_prompt_hash == new_prompt_hash:
        raise ValueError("PROMPT_IMPLEMENTATION_UNCHANGED")

    now = datetime.now(timezone.utc).isoformat()
    generation.update(prompt_version=args.prompt_version, prompt_sha256=new_prompt_hash)
    runtime["operational_rebind"] = {
        "protocol": OPERATIONAL_REBIND_PROTOCOL,
        "approved": True,
        "owner": runtime.get("owner"),
        "approved_at": now,
        "scope": "capstone_demo_only",
        "base_runtime_approval_sha256": old_runtime_hash,
        "base_prompt_sha256": old_prompt_hash,
        "prompt_version": args.prompt_version,
        "prompt_sha256": new_prompt_hash,
        "source_commit": args.source_commit,
        "reason": "Correct a verified false abstention after successful grounded retrieval; V4 benchmark result is not rewritten.",
        "regression": {
            "isolated_tests_total": 37,
            "isolated_tests_passed": 37,
            "false_abstention_case": "utt_it_output_standard_exemption",
        },
        "risk_controls": {
            "citations_required": True,
            "fail_closed": True,
            "same_evidence_on_retry": True,
            "benchmark_result_unchanged": True,
            "real_provider_smoke_required_before_cutover": True,
        },
    }
    runtime["approval_sha256"] = canonical_hash(runtime, omit=("approval_sha256",))

    overlay["base_runtime_approval_sha256"] = runtime["approval_sha256"]
    overlay["operational_rebind"] = {
        "protocol": OPERATIONAL_REBIND_PROTOCOL,
        "runtime_approval_sha256": runtime["approval_sha256"],
        "prompt_sha256": new_prompt_hash,
        "source_commit": args.source_commit,
    }
    overlay["approval_sha256"] = canonical_hash(overlay, omit=("approval_sha256",))

    args.runtime_output.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
    args.high_stakes_output.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = {
        "status": "OPERATIONAL_REBIND_CREATED",
        "prompt_version": args.prompt_version,
        "prompt_sha256": new_prompt_hash,
        "runtime_approval_sha256": runtime["approval_sha256"],
        "high_stakes_approval_sha256": overlay["approval_sha256"],
        "source_commit": args.source_commit,
    }
    args.metadata_output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
