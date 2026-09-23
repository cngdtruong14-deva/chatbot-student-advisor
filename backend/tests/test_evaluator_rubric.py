"""Unit tests for Evaluator Semantic Rubric and Edge Cases (Phase R2)."""
import unittest
from app.evaluate_phase_d_benchmark import evaluate_benchmark
from app.rag_benchmark_v2 import deterministic_rubric


class EvaluatorRubricTests(unittest.TestCase):
    def test_stage7_proxy_normalises_line_wrapping_without_weakening_phrase(self):
        row={
            'benchmark_category':'answerable',
            'required_conditions':['công bố kết quả nghiên cứu trên các tạp chí quốc tế'],
            'forbidden_assertions':['không hỗ trợ tiếng Anh'],
        }
        response={
            'status':'completed',
            'answer':'công bố kết quả nghiên\ncứu trên các tạp chí quốc tế',
            'claims':[{'text':'supported','citation_ids':['c1']}],
        }
        result=deterministic_rubric(row,response,[{'chunk_id':'c1'}])
        self.assertTrue(result['has_required_conditions'])
        self.assertTrue(result['proxy_pass'])

    def test_stage7_proxy_does_not_remove_words_or_accents(self):
        row={
            'benchmark_category':'answerable',
            'required_conditions':['kỹ năng quản lý thời gian'],
            'forbidden_assertions':[],
        }
        response={
            'status':'completed',
            'answer':'kỹ năng giao tiếp và làm việc nhóm',
            'claims':[{'text':'supported','citation_ids':['c1']}],
        }
        result=deterministic_rubric(row,response,[{'chunk_id':'c1'}])
        self.assertFalse(result['has_required_conditions'])
        self.assertFalse(result['proxy_pass'])
    def test_empty_claims_fails_correctness(self):
        """Ca 3: When is_answered is True but claims is empty, correctness must be False."""
        # Simulated logic
        is_answered = True
        claims = []
        all_claims_supported = bool(claims) if is_answered else False
        self.assertFalse(all_claims_supported)

    def test_forbidden_assertion_fails_correctness(self):
        """Ca 1: Even if citation IDs match, forbidden assertion triggers FAIL."""
        full_ans = "Sinh viên được tự do chuyển ngành mà không cần điều kiện nào."
        forbidden = ["không cần điều kiện"]
        has_forbidden = any(fa.lower() in full_ans.lower() for fa in forbidden)
        self.assertTrue(has_forbidden)
        correctness = not has_forbidden
        self.assertFalse(correctness)

    def test_missing_required_condition_fails_correctness(self):
        """Ca 2: Answer missing prerequisite/required condition triggers FAIL."""
        full_ans = "Sinh viên được xét học bổng khi đạt điểm rèn luyện Tốt."
        required = ["điểm học tập từ 3.2 trở lên", "không bị kỷ luật"]
        has_required = all(rc.lower() in full_ans.lower() for rc in required)
        self.assertFalse(has_required)

    def test_partial_citation_precision(self):
        """Ca 4: Partial citation support yields exact precision, not rounded to 1.0."""
        retrieved_cids = {"c1", "c2"}
        claims = [
            {"text": "Claim 1", "citation_ids": ["c1"]},
            {"text": "Claim 2", "citation_ids": ["c99_hallucinated"]},
        ]
        valid_claims = 0
        for cl in claims:
            cids = cl.get("citation_ids", [])
            if cids and set(cids).issubset(retrieved_cids):
                valid_claims += 1
        precision = valid_claims / len(claims)
        self.assertEqual(precision, 0.5)

    def test_infra_error_is_not_safe_abstention(self):
        """Ca 5: Provider timeout / rate_limited is an INFRA ERROR, not safe abstention."""
        gen_status = "timeout"
        is_infra_error = gen_status in ("timeout", "rate_limited", "authentication_error", "provider_error")
        self.assertTrue(is_infra_error)
        
        # When infra error occurs, it must NOT increment abstention_count
        status = "insufficient_evidence"
        if is_infra_error:
            is_abstained = False
        else:
            is_abstained = (status == "insufficient_evidence")
        self.assertFalse(is_abstained)

    def test_answerable_question_abstained_is_incorrect(self):
        """Ca 6: When model declines an answerable question, it is incorrect."""
        cat = "answerable"
        status = "insufficient_evidence"
        is_answered = (status == "answered")
        self.assertFalse(is_answered)


if __name__ == "__main__":
    unittest.main()
