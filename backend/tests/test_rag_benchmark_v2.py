"""Protocol tests for the fail-closed UTT RAG Benchmark V2 module.

These tests use synthetic rows and injected callbacks only.  They never open a
database, vector store, or LLM provider.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.rag_benchmark_v2 import (
    BenchmarkProtocolError,
    FinalRunBlocked,
    canonical_jsonl_sha256,
    canonical_sha256,
    evaluate_dataset,
    file_sha256,
    prepare_final_run,
    split_canonical_sha256,
    validate_benchmark_protocol,
)


NOW = "2026-09-20T08:00:00+00:00"
HASH = "a" * 64


def _row(split: str, number: int, category: str) -> dict:
    question_id = f"{split.upper()}-{number:03d}"
    answerable = category == "answerable"
    # Every source/group is split-specific; rows within a split can share a doc.
    source = f"{split}-source-{number // 10}"
    chunk_id = f"{split}-hybrid-{question_id}"
    return {
        "question_id": question_id,
        "split": split,
        "benchmark_category": category,
        "group_id": f"{split}-group-{number // 10}",
        "source_document_id": source,
        "question": f"Câu hỏi duy nhất {split} {number}",
        "reference_answer": f"Gold answer {split} {number}",
        "as_of": "2026-09-20",
        "expected_scope": "utt_corpus",
        "expected_behavior": "answer" if answerable else "abstain",
        "gold_chunk_ids": [chunk_id] if answerable else [],
        "evidence_spans": [{"span_sha256": f"{split}-span-{number}"}],
        "required_conditions": ["required"] if answerable else [],
        "forbidden_assertions": ["forbidden"] if answerable else [],
        "reviewed": True,
        "reviewer": "Owner",
        "reviewed_at": NOW,
    }


def valid_rows() -> list[dict]:
    rows: list[dict] = []
    for split in ("dev", "test"):
        categories = ["answerable"] * 40 + ["insufficient_evidence"] * 10 + ["scope_security_version"] * 10
        rows.extend(_row(split, number, category) for number, category in enumerate(categories, start=1))
    return rows


def valid_ledger(rows: list[dict]) -> dict:
    return {
        "protocol": "utt_rag_benchmark_v2",
        "approved": True,
        "owner": "Owner",
        "reviewed_at": NOW,
        "dataset_canonical_sha256": canonical_jsonl_sha256(rows),
        "split_canonical_sha256": {split: split_canonical_sha256(rows, split) for split in ("dev", "test")},
        "entries": [
            {"question_id": row["question_id"], "reviewed": True, "reviewer": "Owner", "reviewed_at": NOW}
            for row in rows
        ],
    }


class RagBenchmarkV2ProtocolTests(unittest.TestCase):
    def test_valid_protocol_has_exact_distribution_and_hash(self):
        rows = valid_rows()
        result = validate_benchmark_protocol(rows)
        self.assertEqual(result["question_count"], 120)
        self.assertEqual(result["split_counts"], {"dev": 60, "test": 60})
        self.assertEqual(result["composition"]["dev"], {
            "answerable": 40,
            "insufficient_evidence": 10,
            "scope_security_version": 10,
        })
        self.assertEqual(result["dataset_canonical_sha256"], canonical_jsonl_sha256(rows))

    def test_shared_gold_source_or_span_across_splits_is_rejected(self):
        rows = valid_rows()
        # Different questions but same document source means a group/doc split leak.
        rows[60]["source_document_id"] = rows[0]["source_document_id"]
        with self.assertRaisesRegex(BenchmarkProtocolError, "CROSS_SPLIT_SOURCE_DOCUMENT_LEAKAGE"):
            validate_benchmark_protocol(rows)

    def test_unreviewed_row_cannot_be_used(self):
        rows = valid_rows()
        rows[0]["reviewed"] = False
        with self.assertRaisesRegex(BenchmarkProtocolError, "NOT_REVIEWED"):
            validate_benchmark_protocol(rows)

    def test_evaluator_calls_actual_callback_without_gold_or_reference_answer(self):
        rows = valid_rows()
        callback_contexts: list[dict] = []

        def retrieve(question, context, method, top_k):
            del question, top_k
            return [{
                "score": 0.99,
                "chunk": {
                    "chunk_id": f"{context['split']}-{method}-{context['question_id']}",
                    "text": "Evidence text",
                    "document_id": context["question_id"],
                    "source": "synthetic-test",
                },
            }]

        def actual_answer(question, candidates, context):
            self.assertNotIn("reference_answer", context)
            self.assertNotIn("gold_chunk_ids", context)
            self.assertNotIn("required_conditions", context)
            callback_contexts.append(dict(context))
            if context["benchmark_category"] == "answerable":
                return {
                    "status": "answered",
                    "answer": f"Actual generated answer required for {question}",
                    "claims": [{"text": "Actual generated answer required", "citation_ids": [candidates[0]["chunk_id"]]}],
                    "citations": [{"chunk_id": candidates[0]["chunk_id"]}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                    "provider": {"provider": "fake", "model": "fake-model"},
                    "prompt": {"version": "p1", "sha256": HASH},
                }
            return {"status": "insufficient_evidence", "answer": None, "claims": [], "citations": []}

        report = evaluate_dataset(
            rows,
            split="dev",
            retrieve=retrieve,
            answer=actual_answer,
            methods=("lexical", "dense", "hybrid"),
            answer_method="hybrid",
            runtime_binding={"provider": {"provider": "fake", "model": "fake-model"}, "prompt": {"version": "p1", "sha256": HASH}},
        )
        self.assertEqual(len(callback_contexts), 60)
        self.assertEqual(report["results"][0]["actual_response"]["answer"].split()[0], "Actual")
        self.assertEqual(report["quality"]["scope_leakage_count"], 0)
        self.assertTrue(report["quality"]["owner_review_required"])
        self.assertFalse(report["quality"]["automatically_approved"])
        self.assertEqual(report["retrieval_metrics"]["hybrid"]["hit_at_5"], 1.0)

    def test_final_preflight_rejects_existing_checkpoint_without_running(self):
        rows = valid_rows()
        ledger = valid_ledger(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_path = root / "benchmark.jsonl"
            dataset_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            ledger_path = root / "ledger.json"
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            receipt_path = root / "receipt.json"
            manifest_path = root / "manifest.json"
            receipt_path.write_text(json.dumps({"release_id": "UTT-V2"}), encoding="utf-8")
            manifest_path.write_text(json.dumps({"release_id": "UTT-V2"}), encoding="utf-8")
            retriever = {"version": "r1", "sha256": HASH}
            prompt = {"version": "p1", "sha256": HASH}
            provider = {"version": "provider-v1", "sha256": HASH, "provider": "fake", "model": "fake-model"}
            provenance = {
                "source_kind": "clean_git_commit_source_archive",
                "clean_tree": True,
                "git_commit": "b" * 40,
                "source_archive_sha256": HASH,
            }
            approval = {
                "freeze_version": "utt_rag_benchmark_v2_freeze/1",
                "approved": True,
                "owner": "Owner",
                "approved_at": NOW,
                "dataset": {
                    "canonical_sha256": canonical_jsonl_sha256(rows),
                    "split_canonical_sha256": {
                        split: split_canonical_sha256(rows, split) for split in ("dev", "test")
                    },
                },
                "final_split": "test",
                "review_ledger": {"canonical_sha256": canonical_sha256(ledger)},
                "release": {
                    "release_id": "UTT-V2",
                    "receipt_sha256": file_sha256(receipt_path),
                    "manifest_sha256": file_sha256(manifest_path),
                },
                "retriever": retriever,
                "prompt": prompt,
                "provider": provider,
                "source_provenance": provenance,
            }
            approval_path = root / "approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            output = root / "output"
            output.mkdir()
            checkpoint = output / "final_results_checkpoint.jsonl"
            checkpoint.write_text("prior run", encoding="utf-8")
            with self.assertRaisesRegex(FinalRunBlocked, "FINAL_OUTPUT_OR_CHECKPOINT_ALREADY_EXISTS"):
                prepare_final_run(
                    dataset_path=dataset_path,
                    review_ledger_path=ledger_path,
                    approval_path=approval_path,
                    release_receipt_path=receipt_path,
                    release_manifest_path=manifest_path,
                    output_dir=output,
                    runtime_binding={
                        "release_id": "UTT-V2",
                        "retriever": retriever,
                        "prompt": prompt,
                        "provider": provider,
                        "source_provenance": provenance,
                    },
                )
            checkpoint.unlink()
            preflight = prepare_final_run(
                dataset_path=dataset_path,
                review_ledger_path=ledger_path,
                approval_path=approval_path,
                release_receipt_path=receipt_path,
                release_manifest_path=manifest_path,
                output_dir=output,
                runtime_binding={
                    "release_id": "UTT-V2",
                    "retriever": retriever,
                    "prompt": prompt,
                    "provider": provider,
                    "source_provenance": provenance,
                },
            )
            self.assertEqual(preflight["status"], "PREPARED_NOT_STARTED")
            self.assertTrue(preflight["will_not_write_output"])


if __name__ == "__main__":
    unittest.main()
