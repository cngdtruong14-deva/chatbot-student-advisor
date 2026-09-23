"""Unit tests for the shared RAG benchmark adapter."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.rag_benchmark_adapter import (
    _answer_method_from_binding,
    _provider_matches,
    make_shared_generator,
    make_shared_retriever,
)
from app.rag_benchmark_v2 import BenchmarkProtocolError


class BenchmarkAdapterTests(unittest.TestCase):
    def test_answer_method_is_bound_to_frozen_retriever(self):
        binding = {"retriever": {"method": "keyword"}}
        self.assertEqual(
            _answer_method_from_binding(binding, ("keyword", "dense", "hybrid")),
            "keyword",
        )

    def test_answer_method_binding_fails_closed_when_not_evaluated(self):
        binding = {"retriever": {"method": "other"}}
        with self.assertRaisesRegex(BenchmarkProtocolError, "RUNTIME_BINDING_ANSWER_METHOD_INVALID"):
            _answer_method_from_binding(binding, ("keyword", "dense", "hybrid"))

    def test_shared_retriever_delegates_to_knowledge_retriever(self):
        chunks = [{"chunk_id": "c1", "text": "Quy chế đào tạo", "scope": "utt_corpus"}]
        with patch("app.knowledge.accessible_chunks", return_value=chunks) as mock_acc, \
             patch("app.knowledge.retrieve_candidates", return_value=[{"chunk": chunks[0], "score": 0.95}]) as mock_ret:
            retriever = make_shared_retriever(corpus_scope="utt_corpus", chunks_cache=chunks)
            res = retriever("Điều kiện tốt nghiệp?", {"as_of": "2026-09-20"}, "hybrid", 5)

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["chunk"]["chunk_id"], "c1")
        mock_ret.assert_called_once()

    def test_shared_generator_returns_insufficient_evidence_when_empty(self):
        generator = make_shared_generator(corpus_scope="utt_corpus")
        res = generator("Câu hỏi không có trong kho?", [], {"retrieval_method": "hybrid"})
        self.assertEqual(res["status"], "insufficient_evidence")
        self.assertIsNone(res["answer"])
        self.assertEqual(res["claims"], [])

    def test_shared_generator_controlled_mode_when_approval_missing(self):
        candidates = [
            {
                "chunk": {
                    "chunk_id": "c1",
                    "text": "Điều kiện",
                    "source": "gdrive:test",
                    "section": "Điều 1",
                    "is_effective_date_verified": False,
                },
                "score": 0.8,
            }
        ]
        generator = make_shared_generator(corpus_scope="utt_corpus")
        res = generator("Điều kiện xét tuyển?", candidates, {"retrieval_method": "hybrid"})
        self.assertEqual(res["status"], "controlled_retrieval")
        self.assertIsNone(res["answer"])
        self.assertEqual(res["citations"][0]["chunk_id"], "c1")

    def test_provider_matches_reconstructs_evaluator_safe_candidate(self):
        matches = _provider_matches([{
            "chunk_id": "c1",
            "score": 0.8,
            "evidence_text": "Nội dung bằng chứng",
            "source": "gdrive:test",
            "section": "Điều 1",
            "release_id": "UTT-CORPUS-2026-V2",
        }])
        self.assertEqual(matches[0]["chunk"]["chunk_id"], "c1")
        self.assertEqual(matches[0]["chunk"]["text"], "Nội dung bằng chứng")
        self.assertNotIn("reference_answer", matches[0]["chunk"])
        self.assertNotIn("gold_chunk_ids", matches[0]["chunk"])


if __name__ == "__main__":
    unittest.main()
