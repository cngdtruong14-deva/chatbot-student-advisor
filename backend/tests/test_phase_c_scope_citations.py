"""Tests for Phase C Scope Guardrails, Cohort Boundaries, and Honest Citations."""
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from advisor_core.legal_chunker import chunk_hierarchical_legal
from app.chat_service import dispatch


class PhaseCScopeAndCitationTests(unittest.TestCase):
    def test_honest_locators_and_no_fake_page_numbers(self):
        doc = """ĐƠN XIN MIỄN GIẢM HỌC PHÍ

Kính gửi: Phòng Công tác học sinh sinh viên
Tôi tên là: Trần Thị B
Mã SV: SV002
"""
        chunks = chunk_hierarchical_legal(
            doc,
            document_id="doc-form-02",
            version_id="UTT-V1",
            scope="utt_corpus",
            source="ĐƠN XIN MIỄN GIẢM HỌC PHÍ.docx",
            valid_from="2026-09-19",
        )
        self.assertEqual(len(chunks), 1)
        c = chunks[0]
        self.assertIsNone(c["page_number"])
        self.assertIn("Biểu mẫu", c["locator_label"])
        self.assertNotIn("Trang", c["locator_label"])

    def test_scope_guardrail_cross_major_warning(self):
        user = {"id": uuid4(), "role": "student"}
        student_mock = {"id": uuid4(), "cohort": "K72", "curriculum_id": uuid4()}
        curriculum_mock = {"major": "CNTT"}

        citations_mock = [{
            "chunk_id": "c1",
            "version_id": "UTT-V1",
            "source": "CTDT_XayDung.pdf",
            "section": "Trang 3, Điều 4",
            "excerpt": "Sinh viên ngành Kỹ thuật Xây dựng cần hoàn thành 150 tín chỉ.",
            "major": "Xay Dung",
            "cohort": "all",
            "page_number": 3,
            "locator_label": "Trang 3, Điều 4",
            "is_effective_date_verified": False,
        }]

        mock_search_result = {
            "status": "answered",
            "generation_status": "completed",
            "answer": "Theo CTDT Xây dựng, cần hoàn thành 150 tín chỉ.",
            "claims": [{"text": "Cần hoàn thành 150 tín chỉ", "citation_ids": ["c1"]}],
            "citations": citations_mock,
        }

        with patch("app.api.transaction"), \
             patch("app.api.own_student", return_value=student_mock), \
             patch("app.api.one", return_value=curriculum_mock), \
             patch("app.knowledge.resolve_actor_scope", return_value={"major": "CNTT", "cohort": "K72", "resolved": True}), \
             patch("app.knowledge.search", return_value=mock_search_result):

            res = dispatch("Cho tôi hỏi về ngành Xây dựng cần bao nhiêu tín chỉ?", user, corpus_scope="utt_corpus")
            self.assertEqual(res["status"], "completed")
            self.assertIn("[Cảnh báo phạm vi ngành]", res["answer"])
            self.assertIn("CNTT", res["answer"])
            self.assertIn("Kỹ thuật Xây dựng", res["answer"])
            self.assertEqual(len(res["citations"]), 1)
            self.assertEqual(res["citations"][0]["locator_label"], "Trang 3, Điều 4")

    def test_cohort_boundary_guardrail_for_k72_student(self):
        user = {"id": uuid4(), "role": "student"}
        student_mock = {"id": uuid4(), "cohort": "K72", "curriculum_id": uuid4()}
        curriculum_mock = {"major": "CNTT"}

        citations_mock = [{
            "chunk_id": "c2",
            "version_id": "UTT-V1",
            "source": "1710_QD_QuyCheDaoTao.pdf",
            "section": "Trang 2, Điều 2",
            "excerpt": "Quy chế này có hiệu lực kể từ ngày ký, áp dụng đối với các khóa tuyển sinh từ khóa 75 về sau.",
            "cohort": "K75+",
            "major": "all",
            "page_number": 2,
            "locator_label": "Trang 2, Điều 2",
            "is_effective_date_verified": False,
        }]

        mock_search_result = {
            "status": "answered",
            "generation_status": "completed",
            "answer": "Quy chế đào tạo mới áp dụng từ Khóa 75.",
            "claims": [{"text": "Áp dụng từ K75", "citation_ids": ["c2"]}],
            "citations": citations_mock,
        }

        with patch("app.api.transaction"), \
             patch("app.api.own_student", return_value=student_mock), \
             patch("app.api.one", return_value=curriculum_mock), \
             patch("app.knowledge.resolve_actor_scope", return_value={"major": "CNTT", "cohort": "K72", "resolved": True}), \
             patch("app.knowledge.search", return_value=mock_search_result):

            res = dispatch("Quy chế đào tạo áp dụng như thế nào?", user, corpus_scope="utt_corpus")
            self.assertEqual(res["status"], "completed")
            self.assertIn("[Lưu ý phạm vi khóa]", res["answer"])
            self.assertIn("K72", res["answer"])
            self.assertIn("Khóa 75", res["answer"])


    def test_accessible_chunks_scope_filtering_and_retriever(self):
        from app.knowledge import _scope_matches, retrieve_candidates
        
        test_chunks = [
            {"chunk_id": "c_all", "text": "Quy định chung toàn trường", "major": "all", "cohort": "all", "scope": "utt_corpus", "section": "Điều 1", "valid_from": "2026-01-01", "valid_until": "9999-12-31"},
            {"chunk_id": "c_cntt", "text": "Quy chế đồ án tốt nghiệp ngành CNTT", "major": "CNTT", "cohort": "all", "scope": "utt_corpus", "section": "Điều 2", "valid_from": "2026-01-01", "valid_until": "9999-12-31"},
            {"chunk_id": "c_httt", "text": "Quy chế đồ án chuyên ngành HTTT", "major": "HTTT", "cohort": "all", "scope": "utt_corpus", "section": "Điều 3", "valid_from": "2026-01-01", "valid_until": "9999-12-31"},
            {"chunk_id": "c_k75", "text": "Quy định học phí từ khóa 75", "major": "all", "cohort": "K75+", "scope": "utt_corpus", "section": "Điều 4", "valid_from": "2026-01-01", "valid_until": "9999-12-31"},
        ]

        # An unlinked authenticated student is represented by the literal
        # ``all`` scope: general documents match, major/cohort-specific ones do not.
        self.assertTrue(_scope_matches('all', 'all'))
        self.assertFalse(_scope_matches('CNTT', 'all'))
        self.assertFalse(_scope_matches('K75+', 'all', cohort_mode=True))

        # Test lexical search
        lex = retrieve_candidates("CNTT", test_chunks, method="lexical", top_k=2, corpus_scope="utt_corpus")
        self.assertTrue(len(lex) > 0)
        self.assertEqual(lex[0]["chunk"]["chunk_id"], "c_cntt")

        # Test hybrid search RRF
        with patch("app.dense_runtime.search", return_value=[{"chunk": test_chunks[1], "score": 0.9}]):
            hybrid = retrieve_candidates("CNTT", test_chunks, method="hybrid", top_k=2, corpus_scope="utt_corpus")
            self.assertTrue(len(hybrid) > 0)
            self.assertEqual(hybrid[0]["chunk"]["chunk_id"], "c_cntt")


if __name__ == "__main__":
    unittest.main()
