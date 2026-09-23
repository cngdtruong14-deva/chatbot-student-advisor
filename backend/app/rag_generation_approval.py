"""Approval boundary for sending benchmark evidence to an external generator.

This approval is deliberately separate from ``rag_runtime_approval_v2``.  It
only authorizes an isolated benchmark run for one exact dataset split and one
frozen provider/prompt/retriever/source identity.  Passing this gate does not
enable production generation and does not assert that quality gates passed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.rag_benchmark_v2 import (
    BenchmarkProtocolError,
    canonical_sha256,
    split_canonical_sha256,
    validate_benchmark_protocol,
)


PROTOCOL = "rag_benchmark_generation_v3"
USAGE_SCOPE = "isolated_benchmark_only"
HEX64 = re.compile(r"^[a-f0-9]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")


class BenchmarkGenerationBlocked(BenchmarkProtocolError):
    """Raised before a provider object may be constructed."""


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkGenerationBlocked(code)
    return value.strip()


def _require_hash(value: Any, code: str) -> str:
    value = _require_text(value, code)
    if not HEX64.fullmatch(value):
        raise BenchmarkGenerationBlocked(code)
    return value


def _same(expected: Any, actual: Any, code: str) -> None:
    if canonical_sha256(expected) != canonical_sha256(actual):
        raise BenchmarkGenerationBlocked(code)


def _validate_final_freeze_binding(freeze_approval: Mapping[str, Any], approval: Mapping[str, Any], split: str) -> None:
    if split != "test" or freeze_approval.get("final_split") != "test":
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_FINAL_SPLIT_INVALID")
    dataset = approval.get("dataset")
    freeze_dataset = freeze_approval.get("dataset")
    if not isinstance(dataset, Mapping) or not isinstance(freeze_dataset, Mapping):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_FREEZE_DATASET_BINDING_REQUIRED")
    if freeze_dataset.get("canonical_sha256") != dataset.get("canonical_sha256"):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_FREEZE_DATASET_MISMATCH")
    freeze_split_hashes = freeze_dataset.get("split_canonical_sha256")
    if not isinstance(freeze_split_hashes, Mapping) or freeze_split_hashes.get("test") != dataset.get("split_canonical_sha256"):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_FREEZE_TEST_SPLIT_MISMATCH")
    for name in ("release", "retriever", "prompt", "provider", "source_provenance"):
        _same(freeze_approval.get(name), approval.get(name), f"BENCHMARK_GENERATION_FREEZE_{name.upper()}_MISMATCH")


def load_approval(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_APPROVAL_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_APPROVAL_NOT_OBJECT")
    return value


def validate_generation_approval(
    approval: Mapping[str, Any],
    *,
    rows: Sequence[Mapping[str, Any]],
    split: str,
    runtime_binding: Mapping[str, Any],
    freeze_approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an isolated-provider approval against exact execution inputs."""
    protocol = validate_benchmark_protocol(rows)
    if split not in ("dev", "test"):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_SPLIT_INVALID")
    if approval.get("protocol") != PROTOCOL or approval.get("usage_scope") != USAGE_SCOPE:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_PROTOCOL_INVALID")
    if approval.get("approved") is not True:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_APPROVAL_REQUIRED")
    _require_text(approval.get("owner"), "BENCHMARK_GENERATION_OWNER_REQUIRED")
    approved_at = _require_text(approval.get("approved_at"), "BENCHMARK_GENERATION_APPROVED_AT_REQUIRED")
    try:
        datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_APPROVED_AT_INVALID") from exc
    declared = _require_hash(approval.get("approval_sha256"), "BENCHMARK_GENERATION_APPROVAL_HASH_REQUIRED")
    material = {key: value for key, value in approval.items() if key != "approval_sha256"}
    if canonical_sha256(material) != declared:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_APPROVAL_HASH_MISMATCH")
    if approval.get("split") != split:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_SPLIT_MISMATCH")

    dataset = approval.get("dataset")
    if not isinstance(dataset, Mapping):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_DATASET_BINDING_REQUIRED")
    if dataset.get("canonical_sha256") != protocol["dataset_canonical_sha256"]:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_DATASET_HASH_MISMATCH")
    if dataset.get("split_canonical_sha256") != split_canonical_sha256(rows, split):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_SPLIT_HASH_MISMATCH")

    for name in ("release", "retriever", "prompt", "provider", "source_provenance", "execution"):
        if not isinstance(approval.get(name), Mapping):
            raise BenchmarkGenerationBlocked(f"BENCHMARK_GENERATION_{name.upper()}_BINDING_REQUIRED")
    for name in ("release", "retriever", "prompt", "provider", "source_provenance", "execution"):
        _same(approval[name], runtime_binding.get(name), f"BENCHMARK_GENERATION_RUNTIME_{name.upper()}_MISMATCH")

    provider = approval["provider"]
    if provider.get("provider") != "gemini":
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_GEMINI_REQUIRED")
    _require_text(provider.get("model"), "BENCHMARK_GENERATION_MODEL_REQUIRED")
    _require_text(provider.get("version"), "BENCHMARK_GENERATION_PROVIDER_VERSION_REQUIRED")
    _require_hash(provider.get("sha256"), "BENCHMARK_GENERATION_PROVIDER_HASH_REQUIRED")
    _require_text(approval["prompt"].get("version"), "BENCHMARK_GENERATION_PROMPT_VERSION_REQUIRED")
    _require_hash(approval["prompt"].get("sha256"), "BENCHMARK_GENERATION_PROMPT_HASH_REQUIRED")
    from app.llm_runtime import prompt_sha256
    if approval["prompt"].get("sha256") != prompt_sha256():
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_PROMPT_IMPLEMENTATION_MISMATCH")
    _require_hash(approval["retriever"].get("sha256"), "BENCHMARK_GENERATION_RETRIEVER_HASH_REQUIRED")

    provenance, execution = approval["source_provenance"], approval["execution"]
    if provenance.get("source_kind") != "clean_git_commit_source_archive" or provenance.get("clean_tree") is not True:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_CLEAN_SOURCE_REQUIRED")
    if not GIT_SHA.fullmatch(str(provenance.get("git_commit") or "")):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_GIT_COMMIT_INVALID")
    _require_hash(provenance.get("source_archive_sha256"), "BENCHMARK_GENERATION_SOURCE_ARCHIVE_HASH_REQUIRED")
    if not IMAGE_DIGEST.fullmatch(str(execution.get("image_digest") or "")):
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_IMAGE_DIGEST_REQUIRED")
    if execution.get("source_mounted") is not False:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_SOURCE_MOUNT_FORBIDDEN")

    if freeze_approval is not None:
        _validate_final_freeze_binding(freeze_approval, approval, split)

    env_expected = {
        "RAG_LLM_PROVIDER": provider["provider"],
        "RAG_LLM_MODEL": provider["model"],
        "RAG_LLM_PROMPT_VERSION": approval["prompt"]["version"],
        "RAG_SOURCE_COMMIT": provenance["git_commit"],
        "RAG_SOURCE_ARCHIVE_SHA256": provenance["source_archive_sha256"],
        "RAG_BENCHMARK_IMAGE_DIGEST": execution["image_digest"],
        "RAG_SOURCE_MOUNTED": "0",
    }
    for key, expected in env_expected.items():
        if os.environ.get(key, "").strip() != str(expected):
            raise BenchmarkGenerationBlocked(f"BENCHMARK_GENERATION_ENV_{key}_MISMATCH")
    if os.environ.get("RAG_LLM_ENABLED", "0").strip().lower() not in {"1", "true", "yes"}:
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_PROVIDER_DISABLED")
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise BenchmarkGenerationBlocked("BENCHMARK_GENERATION_KEY_UNAVAILABLE")
    return dict(approval)


def approval_template(
    *,
    rows: Sequence[Mapping[str, Any]],
    split: str,
    runtime_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an unsigned template; an owner must inspect and approve it."""
    protocol = validate_benchmark_protocol(rows)
    return {
        "protocol": PROTOCOL,
        "usage_scope": USAGE_SCOPE,
        "approved": False,
        "owner": "",
        "approved_at": "",
        "split": split,
        "dataset": {
            "canonical_sha256": protocol["dataset_canonical_sha256"],
            "split_canonical_sha256": split_canonical_sha256(rows, split),
        },
        **{name: runtime_binding.get(name) for name in (
            "release", "retriever", "prompt", "provider", "source_provenance", "execution"
        )},
        "approval_sha256": "SET_AFTER_OWNER_REVIEW",
    }
