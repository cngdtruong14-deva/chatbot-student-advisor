"""Unit coverage for Stage 6's fail-closed UTT retrieval mode.

These tests never load Chroma, connect to a database, or invoke a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import knowledge
from app.llm_runtime import prompt_sha256
from app.rebind_rag_prompt_hotfix import apply as apply_rebind, backup_path, restore as restore_rebind
from app.rag_runtime import (
    APPROVAL_MISSING,
    EFFECTIVE_DATE_UNVERIFIED,
    HIGH_STAKES_RETRIEVAL_ONLY,
    HIGH_STAKES_APPROVAL_PROTOCOL,
    OPERATIONAL_REBIND_PROTOCOL,
    RUNTIME_APPROVAL_PROTOCOL,
    CAPSTONE_WAIVER_PROTOCOL,
    RuntimeDecision,
    canonical_hash,
    decide_generation,
    release_context,
)


def chunk(*, verified=True):
    text = "Thông tin đăng ký học phần được công bố theo lịch."
    return {
        "chunk_id": "a" * 64,
        "version_id": "UTT-CORPUS-2026-V2",
        "release_id": "UTT-CORPUS-2026-V2",
        "text": text,
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source": "gdrive:test-document",
        "title": "Lịch đăng ký học phần",
        "section": "Trang 1, Điều 1",
        "scope": "utt_corpus",
        "valid_from": "2026-01-01",
        "valid_until": "9999-12-31",
        "is_effective_date_verified": verified,
        "document_authority": "official_utt_source",
    }


def write_release_receipt(directory: Path, chunks: list[dict]) -> Path:
    root = hashlib.sha256("\n".join(sorted(
        f"{item['chunk_id']}:{item['text_hash']}" for item in chunks
    )).encode("utf-8")).hexdigest()
    receipt = {
        "release_id": "UTT-CORPUS-2026-V2",
        "corpus_scope": "utt_corpus",
        "chunks_hash": root,
        "source_manifest_hash": "b" * 64,
        "checks": {
            "chunk_count_matched": True,
            "embedding_dimension_verified": True,
            "hashes_verified": True,
            "all_chunks_indexed": True,
            "source_count_matched": True,
            "all_sources_reviewed": True,
            "exclusions_applied": True,
        },
    }
    receipt["receipt_sha256"] = canonical_hash(receipt)
    path = directory / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def write_approval(directory: Path, context: dict, *, threshold=0.5) -> Path:
    approval = {
        "protocol": RUNTIME_APPROVAL_PROTOCOL,
        "approved": True,
        "owner": "Owner",
        "release": context,
        "retriever": {"method": "dense", "minimum_evidence_score": threshold},
        "generation": {
            "provider": "gemini", "model": "fixture-model", "prompt_version": "v2.0.0",
            "prompt_sha256": prompt_sha256(),
            "temperature": 0, "max_output_tokens": 1200,
        },
        "benchmark": {"split": "test", "final_report_sha256": "c" * 64},
        "semantic_review": {
            "approved": True,
            "owner": "Owner",
            "reviewed_at": "2026-09-20T00:00:00Z",
            "entries": [{"question_id": f"V3_TEST_{index:03d}", "approved": True} for index in range(60)],
        },
        "quality_gates": {
            "hit_at_5": True,
            "mrr_at_5": True,
            "safe_abstention": True,
            "citation_precision": True,
            "answer_correctness": True,
            "scope_leakage_zero": True,
        },
    }
    approval["approval_sha256"] = canonical_hash(approval)
    path = directory / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    return path


def write_capstone_approval(directory: Path, context: dict, *, threshold=0.5) -> Path:
    path = write_approval(directory, context, threshold=threshold)
    approval = json.loads(path.read_text(encoding="utf-8"))
    rejected_id = approval["semantic_review"]["entries"][-1]["question_id"]
    approval["semantic_review"].update(approved=False, state="accepted_under_capstone_waiver")
    approval["semantic_review"]["entries"][-1]["approved"] = False
    approval["quality_gates"]["answer_correctness"] = False
    approval["capstone_waiver"] = {
        "protocol": CAPSTONE_WAIVER_PROTOCOL,
        "approved": True,
        "owner": approval["owner"],
        "reviewed_at": "2026-09-21T00:00:00Z",
        "scope": "capstone_demo_only",
        "final_report_sha256": approval["benchmark"]["final_report_sha256"],
        "observed_answer_correctness_proxy": 0.875,
        "minimum_accepted_answer_correctness_proxy": 0.875,
        "semantic_approved_count": 59,
        "accepted_rejected_question_ids": [rejected_id],
        "risk_controls": {
            "citations_required": True,
            "fail_closed": True,
            "high_stakes_retrieval_only": True,
            "release_hash_bound": True,
        },
    }
    approval["approval_sha256"] = canonical_hash(approval, omit=("approval_sha256",))
    path.write_text(json.dumps(approval), encoding="utf-8")
    return path


def write_high_stakes_approval(directory: Path, base_path: Path, context: dict) -> Path:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    overlay = {
        "protocol": HIGH_STAKES_APPROVAL_PROTOCOL,
        "approved": True,
        "owner": base["owner"],
        "approved_at": "2026-09-21T09:30:00Z",
        "scope": "capstone_demo_only",
        "base_runtime_approval_sha256": base["approval_sha256"],
        "release": context,
        "risk_controls": {
            "citations_required": True,
            "fail_closed": True,
            "effective_date_required": True,
            "minimum_evidence_threshold_required": True,
            "high_stakes_warning_required": True,
            "deterministic_logic_excluded": True,
            "release_hash_bound": True,
        },
    }
    overlay["approval_sha256"] = canonical_hash(overlay)
    path = directory / "high-stakes-approval.json"
    path.write_text(json.dumps(overlay), encoding="utf-8")
    return path


def attach_operational_rebind(path: Path) -> None:
    approval = json.loads(path.read_text(encoding="utf-8"))
    old_hash = approval["approval_sha256"]
    current_prompt = approval["generation"]["prompt_sha256"]
    approval["operational_rebind"] = {
        "protocol": OPERATIONAL_REBIND_PROTOCOL,
        "approved": True,
        "owner": approval["owner"],
        "approved_at": "2026-09-25T00:00:00Z",
        "scope": "capstone_demo_only",
        "base_runtime_approval_sha256": old_hash,
        "base_prompt_sha256": "d" * 64,
        "prompt_version": approval["generation"]["prompt_version"],
        "prompt_sha256": current_prompt,
        "source_commit": "e" * 40,
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
    approval["approval_sha256"] = canonical_hash(approval, omit=("approval_sha256",))
    path.write_text(json.dumps(approval), encoding="utf-8")


class ControlledRetrievalModeTests(unittest.TestCase):
    def configured_env(self, **extra):
        values = {
            "RAG_LLM_PROVIDER": "gemini",
            "RAG_LLM_MODEL": "fixture-model",
            "RAG_LLM_PROMPT_VERSION": "v2.0.0",
            "RAG_LLM_ENABLED": "1",
            "GEMINI_API_KEY": "not-a-real-key",
            "RAG_METHOD": "dense",
        }
        values.update(extra)
        return patch.dict(os.environ, values, clear=False)

    def test_missing_runtime_approval_is_retrieval_only(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            receipt_path = write_release_receipt(Path(raw), items)
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=Path(raw) / "missing.json", receipt_path=receipt_path,
            )
        self.assertFalse(decision.generation_allowed)
        self.assertEqual(decision.rag_mode, "beta_controlled")
        self.assertEqual(decision.reason, APPROVAL_MISSING)

    def test_hash_bound_approval_can_allow_non_high_stakes_generation(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            context = release_context(items, receipt_path=receipt_path)
            approval_path = write_approval(directory, context)
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertTrue(decision.generation_allowed)
        self.assertEqual(decision.response_mode, "grounded_generation")
        self.assertEqual(decision.rag_mode, "approved_grounded")

    def test_owner_approved_operational_rebind_preserves_generation_gate(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            approval_path = write_approval(directory, release_context(items, receipt_path=receipt_path))
            attach_operational_rebind(approval_path)
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertTrue(decision.generation_allowed)

    def test_operational_rebind_apply_and_restore_are_hash_bound(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            context = release_context(items, receipt_path=receipt_path)
            approval_path = write_capstone_approval(directory, context)
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["generation"]["prompt_sha256"] = "d" * 64
            approval["approval_sha256"] = canonical_hash(approval, omit=("approval_sha256",))
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            overlay_path = write_high_stakes_approval(directory, approval_path, context)

            result = apply_rebind(
                approval_path, overlay_path, source_commit="e" * 40,
                prompt_version="v4-operational-hotfix-1", backup_suffix="fixture",
            )
            self.assertEqual(result["status"], "OPERATIONAL_REBIND_APPLIED")
            self.assertTrue(backup_path(approval_path, "fixture").is_file())
            rebound = json.loads(approval_path.read_text(encoding="utf-8"))
            self.assertEqual(rebound["generation"]["prompt_sha256"], prompt_sha256())
            self.assertEqual(rebound["operational_rebind"]["base_prompt_sha256"], "d" * 64)

            restored = restore_rebind(approval_path, overlay_path, "fixture")
            self.assertEqual(restored["status"], "OPERATIONAL_REBIND_RESTORED")
            self.assertEqual(json.loads(approval_path.read_text(encoding="utf-8"))["generation"]["prompt_sha256"], "d" * 64)

    def test_operational_rebind_fails_closed_when_control_is_removed(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            approval_path = write_approval(directory, release_context(items, receipt_path=receipt_path))
            attach_operational_rebind(approval_path)
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["operational_rebind"]["risk_controls"]["same_evidence_on_retry"] = False
            approval["approval_sha256"] = canonical_hash(approval, omit=("approval_sha256",))
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertFalse(decision.generation_allowed)
        self.assertEqual(decision.reason, "RAG_RUNTIME_APPROVAL_INVALID")

    def test_high_stakes_query_stays_retrieval_only_despite_approval(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            approval_path = write_approval(directory, release_context(items, receipt_path=receipt_path))
            decision = decide_generation(
                query="Điều kiện xét học bổng là gì?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertFalse(decision.generation_allowed)
        self.assertEqual(decision.reason, HIGH_STAKES_RETRIEVAL_ONLY)

    def test_capstone_waiver_allows_only_non_high_stakes_generation(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            approval_path = write_capstone_approval(directory, release_context(items, receipt_path=receipt_path))
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
            high_stakes = decide_generation(
                query="Điều kiện xét học bổng là gì?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertTrue(decision.generation_allowed)
        self.assertEqual(decision.rag_mode, "approved_grounded_capstone")
        self.assertFalse(high_stakes.generation_allowed)
        self.assertEqual(high_stakes.reason, HIGH_STAKES_RETRIEVAL_ONLY)

    def test_additive_owner_approval_allows_grounded_high_stakes_generation(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            context = release_context(items, receipt_path=receipt_path)
            approval_path = write_capstone_approval(directory, context)
            high_stakes_path = write_high_stakes_approval(directory, approval_path, context)
            decision = decide_generation(
                query="Sinh viên có được miễn chuẩn đầu ra không?",
                matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
                high_stakes_path=high_stakes_path,
            )
        self.assertTrue(decision.generation_allowed)
        self.assertEqual(decision.rag_mode, "approved_grounded_capstone_high_stakes")

    def test_high_stakes_overlay_fails_closed_when_control_is_removed(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            context = release_context(items, receipt_path=receipt_path)
            approval_path = write_capstone_approval(directory, context)
            high_stakes_path = write_high_stakes_approval(directory, approval_path, context)
            overlay = json.loads(high_stakes_path.read_text(encoding="utf-8"))
            overlay["risk_controls"]["high_stakes_warning_required"] = False
            overlay["approval_sha256"] = canonical_hash(overlay, omit=("approval_sha256",))
            high_stakes_path.write_text(json.dumps(overlay), encoding="utf-8")
            decision = decide_generation(
                query="Điều kiện xét học bổng là gì?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
                high_stakes_path=high_stakes_path,
            )
        self.assertFalse(decision.generation_allowed)
        self.assertEqual(decision.reason, HIGH_STAKES_RETRIEVAL_ONLY)

    def test_capstone_waiver_fails_closed_when_safety_control_is_removed(self):
        items = [chunk()]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            approval_path = write_capstone_approval(directory, release_context(items, receipt_path=receipt_path))
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["capstone_waiver"]["risk_controls"]["citations_required"] = False
            approval["approval_sha256"] = canonical_hash(approval, omit=("approval_sha256",))
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertFalse(decision.generation_allowed)
        self.assertEqual(decision.reason, "RAG_RUNTIME_APPROVAL_INVALID")

    def test_unverified_effective_date_stays_retrieval_only_despite_approval(self):
        items = [chunk(verified=False)]
        with tempfile.TemporaryDirectory() as raw, self.configured_env():
            directory = Path(raw)
            receipt_path = write_release_receipt(directory, items)
            approval_path = write_approval(directory, release_context(items, receipt_path=receipt_path))
            decision = decide_generation(
                query="Lịch đăng ký học phần thế nào?", matches=[{"chunk": items[0], "score": 0.9}],
                corpus_scope="utt_corpus", method="dense", chunks=items,
                approval_path=approval_path, receipt_path=receipt_path,
            )
        self.assertFalse(decision.generation_allowed)
        self.assertEqual(decision.reason, EFFECTIVE_DATE_UNVERIFIED)

    def test_controlled_knowledge_search_never_constructs_provider(self):
        items = [chunk(verified=False)]
        with self.configured_env(), \
             patch("app.knowledge.accessible_chunks", return_value=items), \
             patch("app.knowledge.retrieve_candidates", return_value=[{"chunk": items[0], "score": 0.9}]), \
             patch("app.llm_runtime.OpenAICompatibleProvider") as provider:
            result = knowledge.search("Lịch đăng ký học phần thế nào?", corpus_scope="utt_corpus")
        provider.assert_not_called()
        self.assertEqual(result["response_mode"], "retrieval_only")
        self.assertEqual(result["generation_status"], "controlled_retrieval")
        self.assertEqual(result["reason"], EFFECTIVE_DATE_UNVERIFIED)
        self.assertEqual(result["citations"][0]["release_id"], "UTT-CORPUS-2026-V2")

    def test_student_scope_filters_retrieval_but_full_release_drives_integrity_check(self):
        scoped = [chunk()]
        full_release = [chunk(), {**chunk(), "chunk_id": "b" * 64}]
        matches = [{"chunk": scoped[0], "score": 0.9}]
        controlled = RuntimeDecision(False, "retrieval_only", "beta_controlled", APPROVAL_MISSING)
        with self.configured_env(), \
             patch("app.knowledge.accessible_chunks", side_effect=[scoped, full_release]) as accessible, \
             patch("app.knowledge.retrieve_candidates", return_value=matches) as retrieve, \
             patch("app.knowledge.decide_generation", return_value=controlled) as decide:
            result = knowledge.search(
                "Văn phòng Công đoàn UTT ở đâu?", corpus_scope="utt_corpus",
                major="Công nghệ thông tin", cohort="K25-CNTT",
            )
        self.assertEqual(accessible.call_count, 2)
        self.assertIs(retrieve.call_args.args[1], scoped)
        self.assertIs(decide.call_args.kwargs["chunks"], full_release)
        self.assertEqual(result["citations"][0]["chunk_id"], scoped[0]["chunk_id"])

    def test_retrieval_error_does_not_expose_raw_exception(self):
        with self.configured_env(), \
             patch("app.knowledge.accessible_chunks", return_value=[chunk()]), \
             patch("app.knowledge.retrieve_candidates", side_effect=RuntimeError("C:\\\\private\\\\provider-secret")):
            result = knowledge.search("Lịch đăng ký học phần thế nào?", corpus_scope="utt_corpus")
        self.assertEqual(result["retrieval_status"], "unavailable")
        self.assertEqual(result["reason"], "RETRIEVAL_UNAVAILABLE")
        self.assertNotIn("provider-secret", json.dumps(result))

    def test_unresolved_student_scope_never_degrades_to_all_scope(self):
        # This returns before opening a DB transaction, which is important for
        # an unlinked/student-profile lookup failure in an API request.
        self.assertEqual(
            knowledge.accessible_chunks(
                corpus_scope="utt_corpus",
                major=knowledge.UNRESOLVED_SCOPE,
                cohort=knowledge.UNRESOLVED_SCOPE,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
