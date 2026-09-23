"""Fail-closed RAG Benchmark V2 protocol and deterministic evaluator.

This module deliberately has no database, provider, or filesystem side effects
apart from callers explicitly loading/writing JSON files.  A production runner
must inject the *same* retrieval adapter used by the application and an actual
answer callback.  In particular, ``reference_answer`` is never passed to the
answer callback and can therefore never become the measured answer by mistake.

The V1/Phase-D evaluators are retained as historical diagnostics only.  They
must not be used to certify an UTT Corpus V2 release.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import time
import unicodedata
from typing import Any, Callable, Iterable, Mapping, Sequence


PROTOCOL_VERSION = "utt_rag_benchmark_v2"
FREEZE_VERSION = "utt_rag_benchmark_v2_freeze/1"
V3_FREEZE_VERSION = "utt_rag_benchmark_v3_freeze/1"
V4_FREEZE_VERSION = "utt_rag_benchmark_v4_freeze/1"
SPLITS = ("dev", "test")
CATEGORIES = ("answerable", "insufficient_evidence", "scope_security_version")
EXPECTED_COMPOSITION = {
    "answerable": 40,
    "insufficient_evidence": 10,
    "scope_security_version": 10,
}
QUALITY_GATES = {
    "hit_at_5_min": 0.90,
    "mrr_at_5_min": 0.75,
    "safe_abstention_min": 0.95,
    "citation_precision_min": 0.95,
    "answer_correctness_proxy_min": 0.90,
    "scope_leakage_max": 0,
}

QUESTION_FIELDS = (
    "question_id",
    "split",
    "benchmark_category",
    "group_id",
    "source_document_id",
    "question",
    "reference_answer",
    "as_of",
    "expected_scope",
    "expected_behavior",
    "gold_chunk_ids",
    "evidence_spans",
    "required_conditions",
    "forbidden_assertions",
    "reviewed",
    "reviewer",
    "reviewed_at",
)
_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
_SAFE_ANSWER_STATUSES = {"insufficient_evidence", "abstained", "scope_denied", "controlled_retrieval"}
_INFRA_STATUSES = {
    "timeout",
    "rate_limited",
    "authentication_error",
    "provider_error",
    "provider_unavailable",
    "retrieval_unavailable",
    "index_unavailable",
}

__all__ = [
    "BenchmarkProtocolError",
    "FinalRunBlocked",
    "QUALITY_GATES",
    "canonical_json_bytes",
    "canonical_jsonl_sha256",
    "canonical_sha256",
    "evaluate_dataset",
    "file_sha256",
    "load_jsonl",
    "main",
    "prepare_final_run",
    "recommend_dev_method",
    "run_final_evaluation",
    "split_canonical_sha256",
    "validate_benchmark_protocol",
    "validate_final_freeze",
    "validate_freeze_approval",
    "validate_protocol",
]


class BenchmarkProtocolError(ValueError):
    """Raised before a benchmark can influence a selection or final result."""


class FinalRunBlocked(BenchmarkProtocolError):
    """Raised when a final-test invocation does not satisfy every freeze gate."""


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical JSON bytes used for stable, platform-independent hashes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_jsonl_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash rows in order while canonicalising each object, including a newline."""
    digest = sha256()
    for row in rows:
        digest.update(canonical_json_bytes(dict(row)))
        digest.update(b"\n")
    return digest.hexdigest()


def split_canonical_sha256(rows: Sequence[Mapping[str, Any]], split: str) -> str:
    """Canonical hash for one explicit split, preserving JSONL row order."""
    return canonical_jsonl_sha256([row for row in rows if row.get("split") == split])


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BenchmarkProtocolError(f"INVALID_JSONL_LINE:{line_number}") from exc
        if not isinstance(value, dict):
            raise BenchmarkProtocolError(f"JSONL_ROW_NOT_OBJECT:{line_number}")
        rows.append(value)
    return rows


def load_json_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkProtocolError(f"INVALID_{label}_JSON") from exc
    if not isinstance(value, dict):
        raise BenchmarkProtocolError(f"INVALID_{label}_OBJECT")
    return value


def _require_nonempty_string(row: Mapping[str, Any], field: str, question_id: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_{field.upper()}")
    return value.strip()


def _parse_timestamp(value: str, error_code: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchmarkProtocolError(error_code) from exc


def _normalised_question(value: str) -> str:
    return " ".join(value.casefold().split())


def _evidence_fingerprints(row: Mapping[str, Any], question_id: str) -> set[str]:
    spans = row.get("evidence_spans")
    if not isinstance(spans, list):
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_EVIDENCE_SPANS")
    fingerprints: set[str] = set()
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_EVIDENCE_SPAN:{index}")
        # A reviewer must give a stable marker, not just prose which may be edited.
        stable_marker = span.get("chunk_id") or span.get("text_sha256") or span.get("span_sha256")
        if not isinstance(stable_marker, str) or not stable_marker.strip():
            raise BenchmarkProtocolError(f"QUESTION_{question_id}_UNSTABLE_EVIDENCE_SPAN:{index}")
        fingerprints.add(canonical_sha256(span))
    return fingerprints


def _validate_question(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise BenchmarkProtocolError("QUESTION_NOT_OBJECT")
    missing = [field for field in QUESTION_FIELDS if field not in row]
    if missing:
        raise BenchmarkProtocolError(f"QUESTION_MISSING_FIELDS:{','.join(missing)}")

    question_id = _require_nonempty_string(row, "question_id", "UNKNOWN")
    split = _require_nonempty_string(row, "split", question_id)
    if split not in SPLITS:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_SPLIT")
    category = _require_nonempty_string(row, "benchmark_category", question_id)
    if category not in CATEGORIES:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_CATEGORY")
    for field in ("group_id", "source_document_id", "question", "reference_answer", "expected_scope"):
        _require_nonempty_string(row, field, question_id)
    expected_behavior = _require_nonempty_string(row, "expected_behavior", question_id)
    if expected_behavior not in {"answer", "abstain", "deny"}:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_EXPECTED_BEHAVIOR")
    if category == "answerable" and expected_behavior != "answer":
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_ANSWERABLE_MUST_EXPECT_ANSWER")
    if category == "insufficient_evidence" and expected_behavior != "abstain":
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INSUFFICIENT_MUST_EXPECT_ABSTAIN")
    if category == "scope_security_version" and expected_behavior not in {"abstain", "deny"}:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_SCOPE_MUST_EXPECT_ABSTAIN_OR_DENY")

    try:
        datetime.fromisoformat(f"{row['as_of']}T00:00:00")
    except (TypeError, ValueError) as exc:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_AS_OF") from exc

    for field in ("gold_chunk_ids", "required_conditions", "forbidden_assertions"):
        values = row.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise BenchmarkProtocolError(f"QUESTION_{question_id}_INVALID_{field.upper()}")
        if len(values) != len(set(values)):
            raise BenchmarkProtocolError(f"QUESTION_{question_id}_DUPLICATE_{field.upper()}")
    gold_ids = row["gold_chunk_ids"]
    if category == "answerable" and not gold_ids:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_ANSWERABLE_MISSING_GOLD")
    if category != "answerable" and gold_ids:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_NONANSWERABLE_HAS_GOLD")
    _evidence_fingerprints(row, question_id)

    if row.get("reviewed") is not True:
        raise BenchmarkProtocolError(f"QUESTION_{question_id}_NOT_REVIEWED")
    _require_nonempty_string(row, "reviewer", question_id)
    reviewed_at = _require_nonempty_string(row, "reviewed_at", question_id)
    _parse_timestamp(reviewed_at, f"QUESTION_{question_id}_INVALID_REVIEWED_AT")
    return dict(row)


def validate_benchmark_protocol(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate the immutable V2 dataset before any retriever/provider is called.

    V2 intentionally rejects legacy category aliases and unreviewed templates.
    This makes a legacy diagnostic file unable to be accidentally used as Final.
    """
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise BenchmarkProtocolError("BENCHMARK_ROWS_NOT_SEQUENCE")
    if len(rows) != 120:
        raise BenchmarkProtocolError(f"BENCHMARK_COUNT_MUST_BE_120_GOT_{len(rows)}")

    validated = [_validate_question(row) for row in rows]
    ids = [row["question_id"] for row in validated]
    if len(ids) != len(set(ids)):
        raise BenchmarkProtocolError("DUPLICATE_QUESTION_ID")
    normalised_questions = [_normalised_question(row["question"]) for row in validated]
    if len(normalised_questions) != len(set(normalised_questions)):
        raise BenchmarkProtocolError("DUPLICATE_OR_OVERLAPPING_QUESTION_TEXT")

    by_split: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    for row in validated:
        by_split[row["split"]].append(row)
    for split, split_rows in by_split.items():
        if len(split_rows) != 60:
            raise BenchmarkProtocolError(f"SPLIT_{split.upper()}_COUNT_MUST_BE_60_GOT_{len(split_rows)}")
        composition = Counter(row["benchmark_category"] for row in split_rows)
        if dict(composition) != EXPECTED_COMPOSITION:
            raise BenchmarkProtocolError(
                f"SPLIT_{split.upper()}_COMPOSITION_INVALID:{dict(sorted(composition.items()))}"
            )

    # Split by both document and clause/group, not merely by textual question IDs.
    dev, test = by_split["dev"], by_split["test"]
    leak_checks = {
        "GROUP": ({row["group_id"] for row in dev}, {row["group_id"] for row in test}),
        "SOURCE_DOCUMENT": ({row["source_document_id"] for row in dev}, {row["source_document_id"] for row in test}),
        "GOLD_CHUNK": (
            {chunk_id for row in dev for chunk_id in row["gold_chunk_ids"]},
            {chunk_id for row in test for chunk_id in row["gold_chunk_ids"]},
        ),
        "EVIDENCE_SPAN": (
            {fingerprint for row in dev for fingerprint in _evidence_fingerprints(row, row["question_id"])},
            {fingerprint for row in test for fingerprint in _evidence_fingerprints(row, row["question_id"])},
        ),
    }
    for label, (left, right) in leak_checks.items():
        leaked = sorted(left & right)
        if leaked:
            raise BenchmarkProtocolError(f"CROSS_SPLIT_{label}_LEAKAGE:{','.join(leaked[:3])}")

    return {
        "protocol": PROTOCOL_VERSION,
        "question_count": len(validated),
        "split_counts": {split: len(by_split[split]) for split in SPLITS},
        "composition": {split: dict(Counter(row["benchmark_category"] for row in by_split[split])) for split in SPLITS},
        "dataset_canonical_sha256": canonical_jsonl_sha256(validated),
        "split_canonical_sha256": {split: split_canonical_sha256(validated, split) for split in SPLITS},
        "question_ids": ids,
    }


def validate_review_ledger(
    ledger: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], dataset_canonical_sha256: str,
) -> dict[str, Any]:
    """Require a signed line-by-line ledger, not a blanket reviewer declaration."""
    if ledger.get("protocol") != PROTOCOL_VERSION:
        raise BenchmarkProtocolError("REVIEW_LEDGER_PROTOCOL_MISMATCH")
    if ledger.get("approved") is not True:
        raise BenchmarkProtocolError("REVIEW_LEDGER_NOT_APPROVED")
    owner = ledger.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise BenchmarkProtocolError("REVIEW_LEDGER_OWNER_REQUIRED")
    reviewed_at = ledger.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        raise BenchmarkProtocolError("REVIEW_LEDGER_REVIEWED_AT_REQUIRED")
    _parse_timestamp(reviewed_at, "REVIEW_LEDGER_INVALID_REVIEWED_AT")
    if ledger.get("dataset_canonical_sha256") != dataset_canonical_sha256:
        raise BenchmarkProtocolError("REVIEW_LEDGER_DATASET_HASH_MISMATCH")
    actual_split_hashes = {split: split_canonical_sha256(rows, split) for split in SPLITS}
    if ledger.get("split_canonical_sha256") != actual_split_hashes:
        raise BenchmarkProtocolError("REVIEW_LEDGER_SPLIT_HASH_MISMATCH")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise BenchmarkProtocolError("REVIEW_LEDGER_ENTRIES_REQUIRED")
    expected = {str(row["question_id"]) for row in rows}
    actual: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise BenchmarkProtocolError("REVIEW_LEDGER_ENTRY_INVALID")
        question_id = entry.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise BenchmarkProtocolError("REVIEW_LEDGER_ENTRY_ID_INVALID")
        if entry.get("reviewed") is not True:
            raise BenchmarkProtocolError(f"REVIEW_LEDGER_ENTRY_NOT_REVIEWED:{question_id}")
        reviewer = entry.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise BenchmarkProtocolError(f"REVIEW_LEDGER_ENTRY_REVIEWER_REQUIRED:{question_id}")
        timestamp = entry.get("reviewed_at")
        if not isinstance(timestamp, str):
            raise BenchmarkProtocolError(f"REVIEW_LEDGER_ENTRY_REVIEWED_AT_REQUIRED:{question_id}")
        _parse_timestamp(timestamp, f"REVIEW_LEDGER_ENTRY_INVALID_REVIEWED_AT:{question_id}")
        actual.add(question_id)
    if actual != expected or len(entries) != len(expected):
        raise BenchmarkProtocolError("REVIEW_LEDGER_QUESTION_SET_MISMATCH")
    return {
        "owner": owner.strip(),
        "entry_count": len(entries),
        "ledger_canonical_sha256": canonical_sha256(dict(ledger)),
    }


def _require_sha(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise FinalRunBlocked(code)
    return value


def _equal_binding(expected: Any, actual: Any, code: str) -> None:
    if canonical_json_bytes(expected) != canonical_json_bytes(actual):
        raise FinalRunBlocked(code)


def _release_id_from(value: Mapping[str, Any]) -> str | None:
    for key in ("release_id", "id", "corpus_release_id"):
        found = value.get(key)
        if isinstance(found, str) and found.strip():
            return found.strip()
    return None


def validate_final_freeze(
    *,
    approval: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    review_ledger: Mapping[str, Any],
    release_receipt_path: str | Path,
    release_manifest_path: str | Path,
    runtime_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate every immutable input of a single final-test run.

    This function does *not* invoke retrieval, a provider, or write lifecycle
    markers.  A runner must call it before it creates any Final checkpoint.
    """
    protocol = validate_benchmark_protocol(rows)
    dataset_hash = protocol["dataset_canonical_sha256"]
    ledger = validate_review_ledger(review_ledger, rows, dataset_hash)

    freeze_version = approval.get("freeze_version")
    if freeze_version not in {FREEZE_VERSION, V3_FREEZE_VERSION, V4_FREEZE_VERSION} or approval.get("approved") is not True:
        raise FinalRunBlocked("FINAL_FREEZE_APPROVAL_REQUIRED")
    if freeze_version in {V3_FREEZE_VERSION, V4_FREEZE_VERSION}:
        declared_approval_hash = approval.get("approval_sha256")
        if not isinstance(declared_approval_hash, str) or not _HEX_64.fullmatch(declared_approval_hash):
            raise FinalRunBlocked("FINAL_FREEZE_APPROVAL_HASH_REQUIRED")
        signed_material = {key: value for key, value in approval.items() if key != "approval_sha256"}
        if canonical_sha256(signed_material) != declared_approval_hash:
            raise FinalRunBlocked("FINAL_FREEZE_APPROVAL_HASH_MISMATCH")
    for field in ("owner", "approved_at"):
        value = approval.get(field)
        if not isinstance(value, str) or not value.strip():
            raise FinalRunBlocked(f"FINAL_FREEZE_{field.upper()}_REQUIRED")
    _parse_timestamp(str(approval["approved_at"]), "FINAL_FREEZE_INVALID_APPROVED_AT")

    dataset = approval.get("dataset")
    ledger_binding = approval.get("review_ledger")
    release = approval.get("release")
    retriever = approval.get("retriever")
    prompt = approval.get("prompt")
    provider = approval.get("provider")
    provenance = approval.get("source_provenance")
    if not all(isinstance(item, Mapping) for item in (dataset, ledger_binding, release, retriever, prompt, provider, provenance)):
        raise FinalRunBlocked("FINAL_FREEZE_BINDING_MISSING")
    if dataset.get("canonical_sha256") != dataset_hash:
        raise FinalRunBlocked("FINAL_FREEZE_DATASET_HASH_MISMATCH")
    if dataset.get("split_canonical_sha256") != protocol["split_canonical_sha256"]:
        raise FinalRunBlocked("FINAL_FREEZE_SPLIT_HASH_MISMATCH")
    if approval.get("final_split") != "test":
        raise FinalRunBlocked("FINAL_FREEZE_FINAL_SPLIT_MUST_BE_TEST")
    if ledger_binding.get("canonical_sha256") != ledger["ledger_canonical_sha256"]:
        raise FinalRunBlocked("FINAL_FREEZE_LEDGER_HASH_MISMATCH")

    receipt = load_json_object(release_receipt_path, "RELEASE_RECEIPT")
    manifest = load_json_object(release_manifest_path, "RELEASE_MANIFEST")
    receipt_sha, manifest_sha = file_sha256(release_receipt_path), file_sha256(release_manifest_path)
    if release.get("receipt_sha256") != receipt_sha:
        raise FinalRunBlocked("FINAL_FREEZE_RECEIPT_HASH_MISMATCH")
    if release.get("manifest_sha256") != manifest_sha:
        raise FinalRunBlocked("FINAL_FREEZE_MANIFEST_HASH_MISMATCH")
    release_id = release.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise FinalRunBlocked("FINAL_FREEZE_RELEASE_ID_REQUIRED")
    if _release_id_from(receipt) != release_id or _release_id_from(manifest) != release_id:
        raise FinalRunBlocked("FINAL_FREEZE_RELEASE_ID_MISMATCH")

    for label, value in (("RETRIEVER", retriever), ("PROMPT", prompt), ("PROVIDER", provider)):
        if not isinstance(value.get("version"), str) or not value.get("version").strip():
            raise FinalRunBlocked(f"FINAL_FREEZE_{label}_VERSION_REQUIRED")
        _require_sha(value.get("sha256"), f"FINAL_FREEZE_{label}_HASH_REQUIRED")
    if not isinstance(provider.get("provider"), str) or not provider.get("provider").strip():
        raise FinalRunBlocked("FINAL_FREEZE_PROVIDER_NAME_REQUIRED")
    if not isinstance(provider.get("model"), str) or not provider.get("model").strip():
        raise FinalRunBlocked("FINAL_FREEZE_PROVIDER_MODEL_REQUIRED")

    if provenance.get("source_kind") != "clean_git_commit_source_archive":
        raise FinalRunBlocked("FINAL_FREEZE_CLEAN_SOURCE_ARCHIVE_REQUIRED")
    if provenance.get("clean_tree") is not True:
        raise FinalRunBlocked("FINAL_FREEZE_DIRTY_SOURCE")
    git_commit = provenance.get("git_commit")
    if not isinstance(git_commit, str) or not _GIT_SHA.fullmatch(git_commit):
        raise FinalRunBlocked("FINAL_FREEZE_GIT_COMMIT_UNKNOWN")
    _require_sha(provenance.get("source_archive_sha256"), "FINAL_FREEZE_SOURCE_ARCHIVE_HASH_REQUIRED")

    runtime_release = runtime_binding.get("release_id")
    if runtime_release != release_id:
        raise FinalRunBlocked("FINAL_RUNTIME_RELEASE_MISMATCH")
    _equal_binding(retriever, runtime_binding.get("retriever"), "FINAL_RUNTIME_RETRIEVER_MISMATCH")
    _equal_binding(prompt, runtime_binding.get("prompt"), "FINAL_RUNTIME_PROMPT_MISMATCH")
    _equal_binding(provider, runtime_binding.get("provider"), "FINAL_RUNTIME_PROVIDER_MISMATCH")
    _equal_binding(provenance, runtime_binding.get("source_provenance"), "FINAL_RUNTIME_PROVENANCE_MISMATCH")

    return {
        "protocol": PROTOCOL_VERSION,
        "dataset_canonical_sha256": dataset_hash,
        "review_ledger_canonical_sha256": ledger["ledger_canonical_sha256"],
        "release_id": release_id,
        "receipt_sha256": receipt_sha,
        "manifest_sha256": manifest_sha,
        "freeze_approval_canonical_sha256": canonical_sha256(dict(approval)),
    }


def prepare_final_run(
    *,
    dataset_path: str | Path,
    review_ledger_path: str | Path,
    approval_path: str | Path,
    release_receipt_path: str | Path,
    release_manifest_path: str | Path,
    output_dir: str | Path,
    runtime_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Preflight exactly one final test without starting it or creating output.

    The caller must separately execute the evaluated run after this returns.  An
    existing output/checkpoint is rejected rather than resumed, so a final test
    is never silently re-run or mixed with an earlier attempt.
    """
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise FinalRunBlocked("FINAL_OUTPUT_OR_CHECKPOINT_ALREADY_EXISTS")
    rows = load_jsonl(dataset_path)
    approval = load_json_object(approval_path, "FINAL_FREEZE_APPROVAL")
    ledger = load_json_object(review_ledger_path, "REVIEW_LEDGER")
    verified = validate_final_freeze(
        approval=approval,
        rows=rows,
        review_ledger=ledger,
        release_receipt_path=release_receipt_path,
        release_manifest_path=release_manifest_path,
        runtime_binding=runtime_binding,
    )
    return {
        "status": "PREPARED_NOT_STARTED",
        "split": "test",
        "will_not_write_output": True,
        "checkpoint_resume_allowed": False,
        **verified,
    }


def _candidate_record(match: Mapping[str, Any], rank: int) -> dict[str, Any]:
    chunk = match.get("chunk", match)
    if not isinstance(chunk, Mapping):
        raise BenchmarkProtocolError("RETRIEVER_RETURNED_INVALID_CANDIDATE")
    chunk_id = chunk.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise BenchmarkProtocolError("RETRIEVER_RETURNED_CANDIDATE_WITHOUT_CHUNK_ID")
    evidence_text = chunk.get("text", chunk.get("content", ""))
    if not isinstance(evidence_text, str):
        evidence_text = ""
    text_hash = chunk.get("text_hash")
    if not isinstance(text_hash, str) or not _HEX_64.fullmatch(text_hash):
        text_hash = sha256(evidence_text.encode("utf-8")).hexdigest()
    return {
        "rank": rank,
        "score": match.get("score"),
        "chunk_id": chunk_id,
        "document_id": chunk.get("document_id"),
        "version_id": chunk.get("version_id"),
        "source": chunk.get("source"),
        "section": chunk.get("section"),
        "page_number": chunk.get("page_number"),
        "release_id": chunk.get("release_id"),
        "evidence_text": evidence_text,
        "evidence_text_sha256": text_hash,
    }


def _safe_callback_context(row: Mapping[str, Any], method: str, top_k: int) -> dict[str, Any]:
    """Only execution context reaches retrieval/generation; never gold labels."""
    return {
        "question_id": row["question_id"],
        "split": row["split"],
        "benchmark_category": row["benchmark_category"],
        "expected_scope": row["expected_scope"],
        "expected_behavior": row["expected_behavior"],
        "as_of": row["as_of"],
        "retrieval_method": method,
        "top_k": top_k,
    }


def _normalise_response(response: Any, runtime_binding: Mapping[str, Any], elapsed_ms: float) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        return {
            "status": "provider_error",
            "answer": None,
            "claims": [],
            "citations": [],
            "usage": {},
            "latency_ms": elapsed_ms,
            "error": "ANSWER_CALLBACK_RETURNED_NON_OBJECT",
            "provider": runtime_binding.get("provider"),
            "prompt": runtime_binding.get("prompt"),
        }
    answer = response.get("answer")
    claims = response.get("claims", [])
    citations = response.get("citations", [])
    return {
        "status": str(response.get("status", response.get("generation_status", "provider_error"))),
        "answer": answer if isinstance(answer, str) else None,
        "claims": list(claims) if isinstance(claims, list) else [],
        "citations": list(citations) if isinstance(citations, list) else [],
        "usage": response.get("usage") if isinstance(response.get("usage"), Mapping) else {},
        "latency_ms": response.get("latency_ms", elapsed_ms),
        "error": response.get("error") or response.get("failure_reason"),
        "provider": response.get("provider", runtime_binding.get("provider")),
        "prompt": response.get("prompt", runtime_binding.get("prompt")),
    }


def deterministic_rubric(
    row: Mapping[str, Any], response: Mapping[str, Any], retrieved: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Deterministic checks are a proxy; semantic truth remains owner-reviewed."""
    status = str(response.get("status", "provider_error"))
    answer = response.get("answer") if isinstance(response.get("answer"), str) else ""
    claims = response.get("claims") if isinstance(response.get("claims"), list) else []
    retrieved_ids = {str(candidate["chunk_id"]) for candidate in retrieved}
    valid_claims = 0
    unsupported_claims = 0
    for claim in claims:
        citation_ids = claim.get("citation_ids") if isinstance(claim, Mapping) else None
        if isinstance(citation_ids, list) and citation_ids and all(
            isinstance(item, str) and item in retrieved_ids for item in citation_ids
        ):
            valid_claims += 1
        else:
            unsupported_claims += 1
    # Line wrapping from OCR and provider rendering must not turn an otherwise
    # exact phrase into a false negative. This deliberately normalises only
    # Unicode representation and whitespace; it does not remove accents,
    # punctuation, words, or weaken any required/forbidden condition.
    def rubric_text(value: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()

    required = [rubric_text(item) for item in row["required_conditions"]]
    forbidden = [rubric_text(item) for item in row["forbidden_assertions"]]
    lower_answer = rubric_text(answer)
    has_required = all(item in lower_answer for item in required)
    has_forbidden = any(item in lower_answer for item in forbidden)
    is_infrastructure_error = status in _INFRA_STATUSES
    category = row["benchmark_category"]

    if is_infrastructure_error:
        return {
            "proxy_label": "infrastructure_error",
            "proxy_pass": False,
            "is_infrastructure_error": True,
            "safe_abstention": False,
            "scope_leakage": False,
            "has_required_conditions": has_required,
            "has_forbidden_assertion": has_forbidden,
            "valid_claim_count": valid_claims,
            "unsupported_claim_count": unsupported_claims,
            "citation_precision_proxy": valid_claims / len(claims) if claims else 0.0,
            "owner_review": {"required": True, "state": "pending", "reason": "infrastructure_error"},
        }

    if category == "answerable":
        answered = status in {"answered", "completed"} and bool(answer)
        supported = bool(claims) and unsupported_claims == 0
        proxy_pass = bool(answered and supported and has_required and not has_forbidden)
        return {
            "proxy_label": "answer_proxy_pass" if proxy_pass else "answer_proxy_fail",
            "proxy_pass": proxy_pass,
            "is_infrastructure_error": False,
            "safe_abstention": False,
            "scope_leakage": False,
            "has_required_conditions": has_required,
            "has_forbidden_assertion": has_forbidden,
            "valid_claim_count": valid_claims,
            "unsupported_claim_count": unsupported_claims,
            "citation_precision_proxy": valid_claims / len(claims) if claims else 0.0,
            "owner_review": {"required": True, "state": "pending", "reason": "semantic_correctness"},
        }

    # Non-answerable cases may show cited excerpts but cannot emit factual claims.
    safe_abstention = status in _SAFE_ANSWER_STATUSES and not claims
    scope_leakage = category == "scope_security_version" and not safe_abstention
    return {
        "proxy_label": "safe_abstention" if safe_abstention else "unsafe_nonanswerable_response",
        "proxy_pass": safe_abstention,
        "is_infrastructure_error": False,
        "safe_abstention": safe_abstention,
        "scope_leakage": scope_leakage,
        "has_required_conditions": has_required,
        "has_forbidden_assertion": has_forbidden,
        "valid_claim_count": valid_claims,
        "unsupported_claim_count": unsupported_claims,
        "citation_precision_proxy": valid_claims / len(claims) if claims else 0.0,
        "owner_review": {"required": True, "state": "pending", "reason": "safety_or_semantics"},
    }


def _retrieval_metrics(rows: Sequence[Mapping[str, Any]], method: str) -> dict[str, float | int]:
    answerable = [row for row in rows if row["benchmark_category"] == "answerable"]
    hit5 = hit1 = 0
    mrr = 0.0
    for row in answerable:
        ids = [candidate["chunk_id"] for candidate in row["retrieval"][method]["candidates"]]
        rank = next((index + 1 for index, chunk_id in enumerate(ids) if chunk_id in row["gold_chunk_ids"]), None)
        if rank is not None:
            hit5 += 1
            mrr += 1.0 / rank
            if rank == 1:
                hit1 += 1
    total = len(answerable)
    return {
        "answerable_count": total,
        "hit_at_1": hit1 / total if total else 0.0,
        "hit_at_5": hit5 / total if total else 0.0,
        "mrr_at_5": mrr / total if total else 0.0,
    }


def recommend_dev_method(retrieval_metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Recommend only an unambiguous Dev winner; never auto-freeze production."""
    if not retrieval_metrics:
        raise BenchmarkProtocolError("NO_RETRIEVAL_METRICS")
    highest = max(
        (float(metrics["hit_at_5"]), float(metrics["mrr_at_5"]))
        for metrics in retrieval_metrics.values()
    )
    candidates = sorted(
        method
        for method, metrics in retrieval_metrics.items()
        if (float(metrics["hit_at_5"]), float(metrics["mrr_at_5"])) == highest
    )
    return {
        "selection_basis": ["hit_at_5", "mrr_at_5"],
        "candidate_methods": candidates,
        "recommended_method": candidates[0] if len(candidates) == 1 else None,
        "requires_owner_selection": len(candidates) != 1,
        "production_frozen": False,
    }


def evaluate_dataset(
    rows: Sequence[Mapping[str, Any]],
    *,
    split: str,
    retrieve: Callable[[str, Mapping[str, Any], str, int], Sequence[Mapping[str, Any]]],
    answer: Callable[[str, Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]],
    methods: Sequence[str],
    answer_method: str,
    runtime_binding: Mapping[str, Any] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Evaluate actual callbacks after strict protocol validation.

    ``retrieve`` receives ``(question, safe_context, method, top_k)`` and
    ``answer`` receives ``(question, selected_candidates, safe_context)``.
    Neither gets the reference answer, gold chunks, conditions, or spans.
    """
    if split not in SPLITS:
        raise BenchmarkProtocolError("EVALUATION_SPLIT_INVALID")
    if not methods or any(not isinstance(method, str) or not method for method in methods):
        raise BenchmarkProtocolError("EVALUATION_METHODS_REQUIRED")
    if len(set(methods)) != len(methods) or answer_method not in methods:
        raise BenchmarkProtocolError("EVALUATION_ANSWER_METHOD_INVALID")
    if top_k != 5:
        # Gate criteria are Hit@5/MRR@5; changing this requires a new protocol.
        raise BenchmarkProtocolError("EVALUATION_TOP_K_MUST_BE_5")
    protocol = validate_benchmark_protocol(rows)
    binding = dict(runtime_binding or {})
    selected_rows = [dict(row) for row in rows if row["split"] == split]
    results: list[dict[str, Any]] = []

    for row in selected_rows:
        retrieval: dict[str, dict[str, Any]] = {}
        selected_candidates: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for method in methods:
            context = _safe_callback_context(row, method, top_k)
            started = time.perf_counter()
            try:
                matches = retrieve(row["question"], context, method, top_k)
                if not isinstance(matches, Sequence) or isinstance(matches, (str, bytes)):
                    raise BenchmarkProtocolError("RETRIEVER_RETURNED_NON_SEQUENCE")
                candidates = [_candidate_record(match, rank) for rank, match in enumerate(matches[:top_k], start=1)]
            except Exception as exc:  # recorded as infrastructure, not safe abstention
                candidates = []
                errors.append({"stage": f"retrieval:{method}", "error": type(exc).__name__})
            elapsed = (time.perf_counter() - started) * 1000.0
            retrieval[method] = {"candidates": candidates, "latency_ms": elapsed}
            if method == answer_method:
                selected_candidates = candidates

        answer_context = _safe_callback_context(row, answer_method, top_k)
        if any(error["stage"] == f"retrieval:{answer_method}" for error in errors):
            response = _normalise_response(
                {"status": "retrieval_unavailable", "error": "SELECTED_RETRIEVER_FAILED"}, binding, 0.0
            )
        else:
            started = time.perf_counter()
            try:
                actual = answer(row["question"], selected_candidates, answer_context)
                response = _normalise_response(actual, binding, (time.perf_counter() - started) * 1000.0)
            except Exception as exc:  # provider errors are observable, never recast as abstention
                errors.append({"stage": "answer", "error": type(exc).__name__})
                response = _normalise_response(
                    {"status": "provider_error", "error": type(exc).__name__},
                    binding,
                    (time.perf_counter() - started) * 1000.0,
                )
        rubric = deterministic_rubric(row, response, selected_candidates)
        results.append(
            {
                "question_id": row["question_id"],
                "split": row["split"],
                "benchmark_category": row["benchmark_category"],
                "group_id": row["group_id"],
                "source_document_id": row["source_document_id"],
                "question": row["question"],
                "as_of": row["as_of"],
                # Gold remains available for deterministic scoring, never callback input.
                "gold_chunk_ids": list(row["gold_chunk_ids"]),
                "retrieval": retrieval,
                "actual_response": response,
                "errors": errors,
                "rubric": rubric,
            }
        )

    metrics = {method: _retrieval_metrics(results, method) for method in methods}
    answerable = [item for item in results if item["benchmark_category"] == "answerable"]
    nonanswerable = [item for item in results if item["benchmark_category"] != "answerable"]
    total_claims = sum(item["rubric"]["valid_claim_count"] + item["rubric"]["unsupported_claim_count"] for item in results)
    valid_claims = sum(item["rubric"]["valid_claim_count"] for item in results)
    infra_errors = sum(1 for item in results if item["rubric"]["is_infrastructure_error"])
    answer_proxy = sum(1 for item in answerable if item["rubric"]["proxy_pass"])
    safe_abstentions = sum(1 for item in nonanswerable if item["rubric"]["safe_abstention"])
    scope_leakage = sum(1 for item in results if item["rubric"]["scope_leakage"])
    selected_metrics = metrics[answer_method]
    quality = {
        "hit_at_5": selected_metrics["hit_at_5"],
        "mrr_at_5": selected_metrics["mrr_at_5"],
        "answer_correctness_proxy": answer_proxy / len(answerable) if answerable else 0.0,
        "safe_abstention": safe_abstentions / len(nonanswerable) if nonanswerable else 0.0,
        "citation_precision_proxy": valid_claims / total_claims if total_claims else 0.0,
        "scope_leakage_count": scope_leakage,
        "infrastructure_error_count": infra_errors,
        "owner_review_required": True,
        "automatically_approved": False,
    }
    quality["thresholds"] = QUALITY_GATES
    quality["thresholds_met_proxy"] = {
        "hit_at_5": quality["hit_at_5"] >= QUALITY_GATES["hit_at_5_min"],
        "mrr_at_5": quality["mrr_at_5"] >= QUALITY_GATES["mrr_at_5_min"],
        "answer_correctness_proxy": quality["answer_correctness_proxy"] >= QUALITY_GATES["answer_correctness_proxy_min"],
        "safe_abstention": quality["safe_abstention"] >= QUALITY_GATES["safe_abstention_min"],
        "citation_precision_proxy": quality["citation_precision_proxy"] >= QUALITY_GATES["citation_precision_min"],
        "scope_leakage": quality["scope_leakage_count"] <= QUALITY_GATES["scope_leakage_max"],
    }
    return {
        "protocol": PROTOCOL_VERSION,
        "split": split,
        "dataset_canonical_sha256": protocol["dataset_canonical_sha256"],
        "retrieval_methods": list(methods),
        "answer_method": answer_method,
        "runtime_binding": binding,
        "results": results,
        "retrieval_metrics": metrics,
        "dev_selection": recommend_dev_method(metrics) if split == "dev" else None,
        "quality": quality,
    }


# Public names retained deliberately short for runners and contract tests.
validate_protocol = validate_benchmark_protocol


def validate_freeze_approval(**kwargs: Any) -> dict[str, Any]:
    """Public fail-closed alias for a V2 Final freeze validation."""
    return validate_final_freeze(**kwargs)


def run_final_evaluation(
    *,
    dataset_path: str | Path,
    review_ledger_path: str | Path,
    approval_path: str | Path,
    release_receipt_path: str | Path,
    release_manifest_path: str | Path,
    output_dir: str | Path,
    runtime_binding: Mapping[str, Any],
    retrieve: Callable[[str, Mapping[str, Any], str, int], Sequence[Mapping[str, Any]]] | None = None,
    answer: Callable[[str, Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]] | None = None,
    methods: Sequence[str] | None = None,
    answer_method: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Explicit final-test entry point with a non-executing default.

    Calling this without ``execute=True`` only returns the strict preflight
    proof.  A caller that does execute must provide injected production adapters;
    this module never imports a legacy evaluator or supplies a reference answer.
    It intentionally does not create lifecycle markers/checkpoints: a release
    runner owns those immutable output files after preflight succeeds.
    """
    preflight = prepare_final_run(
        dataset_path=dataset_path,
        review_ledger_path=review_ledger_path,
        approval_path=approval_path,
        release_receipt_path=release_receipt_path,
        release_manifest_path=release_manifest_path,
        output_dir=output_dir,
        runtime_binding=runtime_binding,
    )
    if execute is not True:
        return preflight
    if retrieve is None or answer is None or not methods or not answer_method:
        raise FinalRunBlocked("FINAL_EXECUTION_CALLBACKS_REQUIRED")
    report = evaluate_dataset(
        load_jsonl(dataset_path),
        split="test",
        retrieve=retrieve,
        answer=answer,
        methods=methods,
        answer_method=answer_method,
        runtime_binding=runtime_binding,
    )
    return {"status": "FINAL_EVALUATED_NOT_PERSISTED", "preflight": preflight, "report": report}


def main(argv: Sequence[str] | None = None) -> int:
    """Run only a no-side-effect Final preflight from the command line.

    Actual Final evaluation requires injected callbacks from the release runner,
    so the CLI cannot accidentally contact a provider or generate a checkpoint.
    """
    import argparse

    parser = argparse.ArgumentParser(description="RAG Benchmark V2 Final preflight (no provider execution)")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--review-ledger", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--release-receipt", required=True)
    parser.add_argument("--release-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runtime-binding", required=True, help="JSON file recorded by the clean release runner")
    args = parser.parse_args(argv)
    runtime_binding = load_json_object(args.runtime_binding, "RUNTIME_BINDING")
    result = prepare_final_run(
        dataset_path=args.dataset,
        review_ledger_path=args.review_ledger,
        approval_path=args.approval,
        release_receipt_path=args.release_receipt,
        release_manifest_path=args.release_manifest,
        output_dir=args.output_dir,
        runtime_binding=runtime_binding,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
