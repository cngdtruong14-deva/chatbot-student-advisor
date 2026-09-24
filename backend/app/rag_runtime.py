"""Fail-closed runtime policy for grounded UTT RAG answers.

This module deliberately contains no provider client.  It decides whether the
caller may *instantiate* a generator only after it verifies a hash-bound,
owner-approved quality record for the exact active release.  Until that record
exists, UTT RAG remains a BETA retrieval experience: citations are returned,
but no language model is asked to draw a conclusion from them.

The approval file is an operational artifact mounted read-only with the corpus;
an environment variable can point to it, but environment variables alone can
never enable grounded generation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


RUNTIME_APPROVAL_PROTOCOL = "rag_runtime_quality_v2"
CAPSTONE_WAIVER_PROTOCOL = "capstone_demo_quality_waiver_v1"
HIGH_STAKES_APPROVAL_PROTOCOL = "capstone_high_stakes_grounded_v1"
RUNTIME_APPROVAL_FILENAME = "rag_runtime_approval_v2.json"
HIGH_STAKES_APPROVAL_FILENAME = "rag_high_stakes_grounded_capstone_v4.signed.json"
RECEIPT_FILENAME = "release_v2_receipt.json"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

# The values are public, stable API/runtime reason codes.  Never return a raw
# file, database, embedding, or provider exception to an end user.
APPROVAL_MISSING = "RAG_RUNTIME_APPROVAL_MISSING"
APPROVAL_INVALID = "RAG_RUNTIME_APPROVAL_INVALID"
APPROVAL_RELEASE_MISMATCH = "RAG_RUNTIME_APPROVAL_RELEASE_MISMATCH"
APPROVAL_PROVIDER_MISMATCH = "RAG_RUNTIME_APPROVAL_PROVIDER_MISMATCH"
APPROVAL_PROMPT_MISMATCH = "RAG_RUNTIME_APPROVAL_PROMPT_MISMATCH"
APPROVAL_METHOD_MISMATCH = "RAG_RUNTIME_APPROVAL_METHOD_MISMATCH"
APPROVAL_THRESHOLD_MISSING = "RAG_RUNTIME_APPROVAL_THRESHOLD_MISSING"
EVIDENCE_BELOW_APPROVED_THRESHOLD = "EVIDENCE_BELOW_APPROVED_THRESHOLD"
HIGH_STAKES_RETRIEVAL_ONLY = "HIGH_STAKES_RETRIEVAL_ONLY"
EFFECTIVE_DATE_UNVERIFIED = "EFFECTIVE_DATE_UNVERIFIED"
NO_EVIDENCE = "NO_EVIDENCE"
PROVIDER_NOT_READY = "PROVIDER_NOT_READY"
RELEASE_CONTEXT_INCOMPLETE = "RAG_RELEASE_CONTEXT_INCOMPLETE"

# These terms are deliberately conservative.  The list is a safety boundary,
# not an intent router: matching one means retrieve/cite only until the owner
# approves a high-stakes generation policy through a future reviewed protocol.
HIGH_STAKES_TERMS = frozenset({
    "hoc bong", "học bổng", "hoc phi", "học phí", "mien giam", "miễn giảm",
    "ky luat", "kỷ luật", "buoc thoi hoc", "buộc thôi học", "dinh chi", "đình chỉ",
    "tot nghiep", "tốt nghiệp", "van bang", "văn bằng", "chuan dau ra", "chuẩn đầu ra",
    "chuyen nganh", "chuyển ngành", "chuyen truong", "chuyển trường",
    "bao luu", "bảo lưu", "thoi hoc", "thôi học", "hoc lai", "học lại",
    "thi lai", "thi lại", "mien thi", "miễn thi", "cong nhan", "công nhận",
    "hoc cung luc hai chuong trinh", "học cùng lúc hai chương trình",
    "quyet dinh", "quyết định", "quy che", "quy chế", "phap ly", "pháp lý",
})


@dataclass(frozen=True)
class RuntimeDecision:
    """A serializable decision made before any provider object is created."""

    generation_allowed: bool
    response_mode: str
    rag_mode: str
    reason: str | None
    approval: Mapping[str, Any] | None = None


def canonical_hash(value: Mapping[str, Any], *, omit: Iterable[str] = ()) -> str:
    """Hash JSON exactly as the corpus manifest/receipt code does."""
    excluded = set(omit)
    normalized = {key: item for key, item in value.items() if key not in excluded}
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _candidate_paths(env_name: str, mounted: Path, repository_relative: tuple[str, ...]) -> list[Path]:
    configured = os.environ.get(env_name, "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(mounted)
    # Local source execution uses ``<repo>/backend/app`` while the image mounts
    # deployment artifacts at /artifacts.  Supporting both does not relax the
    # approval checks below.
    candidates.append(Path(__file__).resolve().parents[2].joinpath(*repository_relative))
    seen: set[str] = set()
    result: list[Path] = []
    for item in candidates:
        marker = str(item)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def runtime_approval_path() -> Path | None:
    for candidate in _candidate_paths(
        "RAG_RUNTIME_APPROVAL_PATH",
        Path("/artifacts/benchmark_v2") / RUNTIME_APPROVAL_FILENAME,
        ("artifacts", "benchmark_v2", RUNTIME_APPROVAL_FILENAME),
    ):
        if candidate.is_file():
            return candidate
    return None


def release_receipt_path() -> Path | None:
    for candidate in _candidate_paths(
        "RAG_RELEASE_RECEIPT_PATH",
        Path("/artifacts/corpus") / RECEIPT_FILENAME,
        ("artifacts", "corpus", RECEIPT_FILENAME),
    ):
        if candidate.is_file():
            return candidate
    return None


def high_stakes_approval_path() -> Path | None:
    for candidate in _candidate_paths(
        "RAG_HIGH_STAKES_APPROVAL_PATH",
        Path("/artifacts/stage7/benchmark_v4") / HIGH_STAKES_APPROVAL_FILENAME,
        ("artifacts", "stage7", "benchmark_v4", HIGH_STAKES_APPROVAL_FILENAME),
    ):
        if candidate.is_file():
            return candidate
    return None


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _normalized(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    ).replace("đ", "d")


def is_high_stakes_query(query: str) -> bool:
    normalized = _normalized(query)
    return any(_normalized(term) in normalized for term in HIGH_STAKES_TERMS)


def _chunk_root_hash(chunks: Iterable[Mapping[str, Any]]) -> str | None:
    pairs: list[str] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        text_hash = str(chunk.get("text_hash") or "")
        if not chunk_id or not SHA256_RE.fullmatch(text_hash):
            return None
        pairs.append(f"{chunk_id}:{text_hash}")
    if not pairs:
        return None
    return hashlib.sha256("\n".join(sorted(pairs)).encode("utf-8")).hexdigest()


def release_context(chunks: Iterable[Mapping[str, Any]], *, receipt_path: Path | None = None) -> dict[str, Any] | None:
    """Build the runtime identity of active UTT chunks and its signed receipt.

    It is deliberately strict: a mixed/legacy release or a receipt that does
    not validate against the active chunk root has no generation path.
    """
    materialized = list(chunks)
    release_ids = {str(chunk.get("release_id") or "") for chunk in materialized}
    release_ids.discard("")
    root = _chunk_root_hash(materialized)
    if len(release_ids) != 1 or root is None:
        return None
    receipt = _load_json(receipt_path if receipt_path is not None else release_receipt_path())
    if not receipt:
        return None
    declared = receipt.get("receipt_sha256")
    if not isinstance(declared, str) or not SHA256_RE.fullmatch(declared):
        return None
    if canonical_hash(receipt, omit=("receipt_sha256",)) != declared:
        return None
    release_id = next(iter(release_ids))
    if receipt.get("release_id") != release_id or receipt.get("chunks_hash") != root:
        return None
    if receipt.get("corpus_scope") != "utt_corpus":
        return None
    required_checks = (
        "chunk_count_matched", "embedding_dimension_verified", "hashes_verified",
        "all_chunks_indexed", "source_count_matched", "all_sources_reviewed", "exclusions_applied",
    )
    if not all(receipt.get("checks", {}).get(name) is True for name in required_checks):
        return None
    source_manifest_hash = receipt.get("source_manifest_hash")
    if not isinstance(source_manifest_hash, str) or not SHA256_RE.fullmatch(source_manifest_hash):
        return None
    return {
        "release_id": release_id,
        "chunks_hash": root,
        "receipt_sha256": declared,
        "source_manifest_hash": source_manifest_hash,
    }


def _provider_identity() -> dict[str, str | bool]:
    provider = os.environ.get("RAG_LLM_PROVIDER", "").strip().lower()
    model = os.environ.get("RAG_LLM_MODEL", "").strip()
    prompt_version = os.environ.get("RAG_LLM_PROMPT_VERSION", "").strip()
    enabled = os.environ.get("RAG_LLM_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    gateway_configured = bool(
        os.environ.get("RAG_LLM_GATEWAY_URL", "").strip()
        and os.environ.get("RAG_LLM_GATEWAY_SECRET", "").strip()
    )
    key_present = bool(
        gateway_configured or os.environ.get("GEMINI_API_KEY", "").strip()
        if provider == "gemini"
        else os.environ.get("RAG_LLM_API_KEY", "").strip()
    )
    return {
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "enabled": enabled,
        "key_present": key_present,
    }


def _quality_passed(approval: Mapping[str, Any]) -> bool:
    gates = approval.get("quality_gates")
    if not isinstance(gates, Mapping):
        return False
    required = (
        "hit_at_5", "mrr_at_5", "safe_abstention", "citation_precision",
        "answer_correctness", "scope_leakage_zero",
    )
    standard_gates_passed = all(gates.get(name) is True for name in required)
    benchmark = approval.get("benchmark")
    if not isinstance(benchmark, Mapping) or benchmark.get("split") != "test" or not SHA256_RE.fullmatch(str(benchmark.get("final_report_sha256") or "")):
        return False
    review = approval.get("semantic_review")
    if not isinstance(review, Mapping):
        return False
    if not isinstance(review.get("owner"), str) or not review["owner"].strip():
        return False
    entries = review.get("entries")
    if not isinstance(entries, list) or len(entries) != 60:
        return False
    approved_ids = {entry.get("question_id") for entry in entries if isinstance(entry, Mapping) and entry.get("approved") is True}
    if standard_gates_passed and review.get("approved") is True:
        return len(approved_ids) == 60 and None not in approved_ids

    # A capstone waiver is deliberately narrower than the normal production
    # gate. It may accept exactly one safe abstention on an answerable row, but
    # it cannot waive retrieval, citations, scope, infrastructure, high-stakes,
    # provider or release protections.
    waiver = approval.get("capstone_waiver")
    if not isinstance(waiver, Mapping) or waiver.get("protocol") != CAPSTONE_WAIVER_PROTOCOL:
        return False
    if waiver.get("approved") is not True or waiver.get("scope") != "capstone_demo_only":
        return False
    if waiver.get("owner") != approval.get("owner") or not waiver.get("reviewed_at"):
        return False
    if waiver.get("final_report_sha256") != benchmark.get("final_report_sha256"):
        return False
    observed = waiver.get("observed_answer_correctness_proxy")
    minimum = waiver.get("minimum_accepted_answer_correctness_proxy")
    if isinstance(observed, bool) or isinstance(minimum, bool) or not isinstance(observed, (int, float)) or not isinstance(minimum, (int, float)):
        return False
    if float(observed) < 0.875 or float(minimum) != 0.875 or float(observed) < float(minimum):
        return False
    if gates.get("answer_correctness") is not False or any(gates.get(name) is not True for name in required if name != "answer_correctness"):
        return False
    rejected = sorted(
        str(entry.get("question_id")) for entry in entries
        if isinstance(entry, Mapping) and entry.get("approved") is not True
    )
    declared_rejected = sorted(str(item) for item in waiver.get("accepted_rejected_question_ids", []))
    if len(approved_ids) != 59 or len(rejected) != 1 or rejected != declared_rejected:
        return False
    controls = waiver.get("risk_controls")
    return isinstance(controls, Mapping) and all(controls.get(name) is True for name in (
        "citations_required", "fail_closed", "high_stakes_retrieval_only", "release_hash_bound",
    ))


def _approval_matches(
    approval: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    method: str,
    provider: Mapping[str, str | bool],
) -> tuple[bool, str | None]:
    if approval.get("protocol") != RUNTIME_APPROVAL_PROTOCOL or approval.get("approved") is not True:
        return False, APPROVAL_INVALID
    if not isinstance(approval.get("owner"), str) or not approval["owner"].strip():
        return False, APPROVAL_INVALID
    declared = approval.get("approval_sha256")
    if not isinstance(declared, str) or not SHA256_RE.fullmatch(declared):
        return False, APPROVAL_INVALID
    if canonical_hash(approval, omit=("approval_sha256",)) != declared:
        return False, APPROVAL_INVALID
    if not _quality_passed(approval):
        return False, APPROVAL_INVALID

    release = approval.get("release")
    if not isinstance(release, Mapping) or any(release.get(key) != context.get(key) for key in (
        "release_id", "chunks_hash", "receipt_sha256", "source_manifest_hash",
    )):
        return False, APPROVAL_RELEASE_MISMATCH

    retriever = approval.get("retriever")
    if not isinstance(retriever, Mapping) or retriever.get("method") != method:
        return False, APPROVAL_METHOD_MISMATCH
    threshold = retriever.get("minimum_evidence_score")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
        return False, APPROVAL_THRESHOLD_MISSING

    generation = approval.get("generation")
    if not isinstance(generation, Mapping) or not isinstance(generation.get("prompt_version"), str) or not generation["prompt_version"].strip():
        return False, APPROVAL_INVALID
    # The current provider request is intentionally deterministic.  Freeze its
    # prompt identifier and fixed decoding contract with the approval rather
    # than allowing a changed environment to silently reuse benchmark results.
    if generation.get("prompt_version") != provider.get("prompt_version"):
        return False, APPROVAL_PROMPT_MISMATCH
    from app.llm_runtime import prompt_sha256
    if generation.get("prompt_sha256") != prompt_sha256():
        return False, APPROVAL_PROMPT_MISMATCH
    if generation.get("temperature") != 0 or generation.get("max_output_tokens") != 1200:
        return False, APPROVAL_INVALID
    if generation.get("provider") != provider["provider"] or generation.get("model") != provider["model"]:
        return False, APPROVAL_PROVIDER_MISMATCH
    return True, None


def validate_runtime_approval(
    approval: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    method: str,
    provider: Mapping[str, str | bool] | None = None,
) -> tuple[bool, str | None]:
    """Public, side-effect-free validator for release tooling and tests.

    It validates the owner/hash/release/provider/retriever binding but does not
    read the network, instantiate an LLM client, or mutate a corpus.
    """
    identity = provider if provider is not None else _provider_identity()
    return _approval_matches(approval, context=context, method=method, provider=identity)


def _any_unverified_effective_date(matches: Iterable[Mapping[str, Any]]) -> bool:
    # A missing verification flag is unverified.  This must remain true even if
    # the document currently has a broad valid_from/valid_until DB interval.
    return any(match.get("chunk", {}).get("is_effective_date_verified") is not True for match in matches)


def _high_stakes_approved(
    overlay: Mapping[str, Any] | None,
    *,
    base_approval: Mapping[str, Any],
    context: Mapping[str, Any],
) -> bool:
    """Validate an additive owner approval without rewriting the frozen V4 approval."""
    if not isinstance(overlay, Mapping) or overlay.get("protocol") != HIGH_STAKES_APPROVAL_PROTOCOL:
        return False
    if overlay.get("approved") is not True or overlay.get("scope") != "capstone_demo_only":
        return False
    if overlay.get("owner") != base_approval.get("owner") or not overlay.get("approved_at"):
        return False
    waiver = base_approval.get("capstone_waiver")
    if not isinstance(waiver, Mapping) or waiver.get("approved") is not True:
        return False
    declared = overlay.get("approval_sha256")
    if not isinstance(declared, str) or not SHA256_RE.fullmatch(declared):
        return False
    if canonical_hash(overlay, omit=("approval_sha256",)) != declared:
        return False
    if overlay.get("base_runtime_approval_sha256") != base_approval.get("approval_sha256"):
        return False
    release = overlay.get("release")
    if not isinstance(release, Mapping) or any(release.get(key) != context.get(key) for key in (
        "release_id", "chunks_hash", "receipt_sha256", "source_manifest_hash",
    )):
        return False
    controls = overlay.get("risk_controls")
    return isinstance(controls, Mapping) and all(controls.get(name) is True for name in (
        "citations_required", "fail_closed", "effective_date_required",
        "minimum_evidence_threshold_required", "high_stakes_warning_required",
        "deterministic_logic_excluded", "release_hash_bound",
    ))


def decide_generation(
    *,
    query: str,
    matches: list[Mapping[str, Any]],
    corpus_scope: str,
    method: str,
    chunks: Iterable[Mapping[str, Any]],
    approval_path: Path | None = None,
    receipt_path: Path | None = None,
    high_stakes_path: Path | None = None,
) -> RuntimeDecision:
    """Return a decision before any LLM/provider object is constructed."""
    # Demo stays compatible with the original provider-neutral fallback.  UTT
    # test data is intentionally not promoted by this decision engine.
    if corpus_scope != "utt_corpus":
        return RuntimeDecision(True, "grounded_generation", "standard", None)
    if not matches:
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", NO_EVIDENCE)
    high_stakes = is_high_stakes_query(query)
    if _any_unverified_effective_date(matches):
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", EFFECTIVE_DATE_UNVERIFIED)

    context = release_context(chunks, receipt_path=receipt_path)
    if context is None:
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", RELEASE_CONTEXT_INCOMPLETE)
    approval = _load_json(approval_path if approval_path is not None else runtime_approval_path())
    if approval is None:
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", APPROVAL_MISSING)
    provider = _provider_identity()
    valid, reason = validate_runtime_approval(approval, context=context, method=method, provider=provider)
    if not valid:
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", reason)
    if high_stakes:
        overlay = _load_json(high_stakes_path if high_stakes_path is not None else high_stakes_approval_path())
        if not _high_stakes_approved(overlay, base_approval=approval, context=context):
            return RuntimeDecision(False, "retrieval_only", "beta_controlled", HIGH_STAKES_RETRIEVAL_ONLY)
    if not provider["enabled"] or not provider["key_present"]:
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", PROVIDER_NOT_READY)
    threshold = float(approval["retriever"]["minimum_evidence_score"])
    top_score = matches[0].get("score")
    if isinstance(top_score, bool) or not isinstance(top_score, (int, float)) or not math.isfinite(float(top_score)) or float(top_score) < threshold:
        return RuntimeDecision(False, "retrieval_only", "beta_controlled", EVIDENCE_BELOW_APPROVED_THRESHOLD)
    rag_mode = ("approved_grounded_capstone_high_stakes" if high_stakes else
                "approved_grounded_capstone" if approval.get("capstone_waiver") else "approved_grounded")
    return RuntimeDecision(True, "grounded_generation", rag_mode, None, approval)


def controlled_note(reason: str | None) -> str:
    """User-safe explanation for evidence-only UTT responses."""
    if reason == NO_EVIDENCE:
        return "Chưa tìm thấy bằng chứng phù hợp trong kho văn bản UTT đã công bố. Hệ thống không suy đoán câu trả lời."
    if reason == HIGH_STAKES_RETRIEVAL_ONLY:
        return "Nội dung này cần được đối chiếu trực tiếp với văn bản và đơn vị phụ trách UTT; hệ thống chỉ hiển thị trích đoạn liên quan."
    if reason == EFFECTIVE_DATE_UNVERIFIED:
        return "Ngày hiệu lực của ít nhất một trích đoạn chưa được xác minh. Hệ thống chỉ hiển thị bằng chứng để bạn đối chiếu."
    if reason == EVIDENCE_BELOW_APPROVED_THRESHOLD:
        return "Bằng chứng truy xuất chưa đạt ngưỡng đã được duyệt để tổng hợp tự động. Hệ thống chỉ hiển thị trích đoạn liên quan."
    return "Kho tài liệu UTT đang ở chế độ BETA an toàn. Hệ thống chỉ hiển thị trích đoạn có dẫn nguồn để bạn đối chiếu."
