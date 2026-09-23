"""Regression: PostgreSQL timestamptz finalization vs date semester end."""
import unittest
from datetime import date, datetime, timezone
from advisor_core.academic_policy_v2 import semester_history


class HistoryDatesTest(unittest.TestCase):
    def test_timestamp_and_date_match(self):
        row = dict(code='IT101', attempt_no=1, credits=3, status='graded',
                   final_score=8, semester_id='term', semester_code='TERM',
                   end_date=date(2026, 6, 30))
        for finalized in (date(2026, 6, 30), datetime(2026, 6, 30, tzinfo=timezone.utc),
                          '2026-06-30T00:00:00+00:00'):
            result = semester_history([dict(row, finalized_at=finalized)])[0]
            self.assertEqual(result['term_gpa'], '3.500000')
            self.assertEqual(result['availability_coverage']['available_rows'], 1)

    def test_future_and_missing_dates_excluded(self):
        row = dict(code='IT101', attempt_no=1, credits=3, status='graded',
                   final_score=8, semester_id='term', semester_code='TERM',
                   end_date=date(2026, 6, 30))
        for finalized in (None, datetime(2026, 7, 1, tzinfo=timezone.utc)):
            result = semester_history([dict(row, finalized_at=finalized)])[0]
            self.assertIsNone(result['term_gpa'])
            self.assertEqual(result['availability_coverage']['available_rows'], 0)


if __name__ == '__main__':
    unittest.main()
