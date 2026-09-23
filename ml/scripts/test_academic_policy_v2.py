import unittest
from advisor_core.academic_policy_v2 import normalize_attempt, preview_attempts, required_gpa, semester_history, summarize


class PolicyTests(unittest.TestCase):
    def row(self, score=8, attempt=1, course='A', credits=3, bearing=True, status='graded'):
        return normalize_attempt(course=course, attempt=attempt, credits=credits, score=score,
                                 gpa_bearing=bearing, status=status)

    def test_weighted_two_scales(self):
        r = summarize([self.row(), self.row(5, course='B', credits=2)])
        self.assertEqual((r['gpa_10'], r['gpa_4']), ('6.800000', '2.700000'))

    def test_absence_is_zero_and_incomplete(self):
        r = summarize([self.row(None, status='absent_or_barred')])
        self.assertEqual((r['gpa_10'], r['gpa_4'], r['gpa_credits']), ('0.000000', '0.000000', '3.000000'))
        self.assertEqual(r['incomplete_courses'], ['A'])

    def test_retake_replaces_absence(self):
        r = summarize([self.row(None, status='absent_or_barred'), self.row(7, attempt=2)])
        self.assertEqual((r['gpa_10'], r['gpa_4'], r['gpa_credits']), ('7.000000', '3.000000', '3.000000'))
        self.assertEqual(r['incomplete_courses'], [])

    def test_latest_lower_score_replaces_highest(self):
        r = summarize([self.row(9), self.row(5, attempt=2)])
        self.assertEqual((r['gpa_10'], r['gpa_4']), ('5.000000', '1.500000'))

    def test_non_gpa_pass_and_fail(self):
        for score, expected in [(3, ['B']), (6, [])]:
            r = summarize([self.row(), self.row(score, course='B', bearing=False)])
            self.assertEqual(r['gpa_4'], '3.500000')
            self.assertEqual(r['non_gpa_incomplete_courses'], expected)

    def test_earned_includes_passed_non_gpa_but_not_gpa_denominator(self):
        r = summarize([self.row(8), self.row(6, course='B', credits=2, bearing=False)])
        self.assertEqual((r['gpa_credits'], r['earned_credits']), ('3.000000', '5.000000'))

    def test_non_gpa_retake(self):
        r = summarize([self.row(2, bearing=False), self.row(6, attempt=2, bearing=False)])
        self.assertIsNone(r['gpa_4'])
        self.assertEqual(r['incomplete_courses'], [])

    def test_empty(self):
        self.assertIsNone(summarize([])['gpa_10'])

    def test_bands(self):
        for score, expected in [(0,'0.000000'), (3.9,'0.000000'), (4,'1.000000'),
                                (5,'1.500000'), (5.5,'2.000000'), (6.5,'2.500000'),
                                (7,'3.000000'), (8,'3.500000'), (8.5,'4.000000'), (10,'4.000000')]:
            self.assertEqual(summarize([self.row(score)])['gpa_4'], expected)

    def test_new_absence_replaces_previous_pass(self):
        r = summarize([self.row(None, attempt=2, status='absent_or_barred'), self.row(9)])
        self.assertEqual(r['gpa_4'], '0.000000')
        self.assertEqual(r['incomplete_courses'], ['A'])

    def test_invalid(self):
        for kwargs in [{'score': None}, {'score': 11}, {'score': 'NaN'}, {'credits': 0}, {'attempt': 1.5}]:
            with self.assertRaises(ValueError): self.row(**kwargs)
        with self.assertRaises(ValueError): summarize([self.row(), self.row()])

    def test_required_gpa_uses_banded_four_point_summary(self):
        summary = summarize([self.row(8)])
        result = required_gpa(summary, '3.5', '3')
        self.assertEqual(result['current_gpa'], '3.500000')
        self.assertEqual(result['required_future_gpa'], '3.500000')
        self.assertEqual(result['policy_version'], 'ACADEMIC-DEMO-2.0.0')

    def test_preview_uses_latest_attempt_and_non_gpa_course(self):
        summary = preview_attempts([
            {'course': 'CS101', 'attempt': 1, 'credits': '3', 'score': '9', 'gpa_bearing': True},
            {'course': 'CS101', 'attempt': 2, 'credits': '3', 'score': '4', 'gpa_bearing': True},
            {'course': 'PE101', 'attempt': 1, 'credits': '1', 'score': '9', 'gpa_bearing': False},
        ])
        self.assertEqual(summary['gpa_4'], '1.000000')
        self.assertEqual(summary['gpa_10'], '4.000000')
        self.assertEqual(summary['earned_credits'], '4.000000')

    def test_semester_history_does_not_invent_missing_finalization_time(self):
        rows = [
            {'code': 'A', 'attempt_no': 1, 'credits': '3', 'final_score': '8', 'status': 'graded',
             'semester_id': 's1', 'semester_code': 'S1', 'end_date': '2025-01-15', 'finalized_at': '2025-01-10'},
            {'code': 'B', 'attempt_no': 1, 'credits': '3', 'final_score': None, 'status': 'incomplete',
             'semester_id': 's1', 'semester_code': 'S1', 'end_date': '2025-01-15', 'finalized_at': None},
        ]
        history = semester_history(rows)
        self.assertEqual(history[0]['cumulative_gpa'], '3.500000')
        self.assertEqual(history[0]['availability_coverage'], {'available_rows': 1, 'unknown_rows_in_scope': 1, 'state': 'partial'})


if __name__ == '__main__': unittest.main()
