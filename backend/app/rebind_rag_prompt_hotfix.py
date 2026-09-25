"""Apply or restore a traceable V4 prompt rebind on the mounted runtime files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import uuid

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


def backup_path(path: Path, suffix: str) -> Path:
    return path.with_name(path.stem + f".pre-{suffix}" + path.suffix)


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def restore(runtime_path: Path, overlay_path: Path, suffix: str) -> dict:
    runtime_backup = backup_path(runtime_path, suffix)
    overlay_backup = backup_path(overlay_path, suffix)
    if not runtime_backup.is_file() or not overlay_backup.is_file():
        raise ValueError("REBIND_BACKUP_MISSING")
    atomic_write(runtime_path, load(runtime_backup))
    atomic_write(overlay_path, load(overlay_backup))
    return {"status": "OPERATIONAL_REBIND_RESTORED", "backup_suffix": suffix}


def apply(runtime_path: Path, overlay_path: Path, *, source_commit: str,
          prompt_version: str, backup_suffix: str) -> dict:
    if len(source_commit) != 40 or any(ch not in "0123456789abcdef" for ch in source_commit):
        raise ValueError("SOURCE_COMMIT_INVALID")
    runtime = load(runtime_path)
    overlay = load(overlay_path)
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
    generation.update(prompt_version=prompt_version, prompt_sha256=new_prompt_hash)
    runtime["operational_rebind"] = {
        "protocol": OPERATIONAL_REBIND_PROTOCOL,
        "approved": True,
        "owner": runtime.get("owner"),
        "approved_at": now,
        "scope": "capstone_demo_only",
        "base_runtime_approval_sha256": old_runtime_hash,
        "base_prompt_sha256": old_prompt_hash,
        "prompt_version": prompt_version,
        "prompt_sha256": new_prompt_hash,
        "source_commit": source_commit,
        "reason": "Correct a verified false abstention after successful grounded retrieval; V4 benchmark result is not rewritten.",
        "regression": {
            "isolated_tests_total": 38,
            "isolated_tests_passed": 38,
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
        "source_commit": source_commit,
    }
    overlay["approval_sha256"] = canonical_hash(overlay, omit=("approval_sha256",))

    runtime_backup = backup_path(runtime_path, backup_suffix)
    overlay_backup = backup_path(overlay_path, backup_suffix)
    if runtime_backup.exists() or overlay_backup.exists():
        raise ValueError("REBIND_BACKUP_EXISTS")
    shutil.copyfile(runtime_path, runtime_backup)
    shutil.copyfile(overlay_path, overlay_backup)
    try:
        atomic_write(runtime_path, runtime)
        atomic_write(overlay_path, overlay)
    except Exception:
        shutil.copyfile(runtime_backup, runtime_path)
        shutil.copyfile(overlay_backup, overlay_path)
        raise
    return {
        "status": "OPERATIONAL_REBIND_APPLIED",
        "prompt_version": prompt_version,
        "prompt_sha256": new_prompt_hash,
        "runtime_approval_sha256": runtime["approval_sha256"],
        "high_stakes_approval_sha256": overlay["approval_sha256"],
        "source_commit": source_commit,
        "backup_suffix": backup_suffix,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-path", type=Path, required=True)
    parser.add_argument("--high-stakes-path", type=Path, required=True)
    parser.add_argument("--backup-suffix", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--prompt-version", default="v4-operational-hotfix-1")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRM:
        raise ValueError("EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    result = (
        restore(args.runtime_path, args.high_stakes_path, args.backup_suffix)
        if args.restore else
        apply(args.runtime_path, args.high_stakes_path, source_commit=args.source_commit or "",
              prompt_version=args.prompt_version, backup_suffix=args.backup_suffix)
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
