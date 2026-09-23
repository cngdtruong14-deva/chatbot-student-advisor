import unittest
from app import academic as a
from copy import deepcopy


def grade(score, attempt=1, **extra):
    return dict(course_id="course", credits="3", status="graded", final_score=score, attempt_no=attempt, **extra)


class AcademicTests(unittest.TestCase):
    def test_gpa_fixture(self):
        rows = [dict(grade("7.4"), course_id=str(i)) for i in range(24)]
        r = a.summary(rows)
        self.assertEqual((r["cumulative_gpa"], r["quality_points"], r["earned_credits"]), ("2.960000", "213.120000", "72.000000"))

    def test_highest_retake_not_latest(self):
        rows = [grade("3"), grade("7", 2), grade("5", 3)]
        before = deepcopy(rows)
        r = a.summary(rows)
        self.assertEqual((r["cumulative_gpa"], r["gpa_credits"], r["earned_credits"]), ("2.800000", "3.000000", "3.000000"))
        self.assertEqual(rows, before)

    def test_failed_score_is_not_forced_zero(self):
        r = a.summary([grade("3")])
        self.assertEqual((r["quality_points"], r["earned_credits"]), ("3.600000", "0.000000"))

    def test_pending_does_not_replace(self):
        r = a.summary([grade("7"), dict(grade(None, 2), status="pending")])
        self.assertEqual(r["cumulative_gpa"], "2.800000")

    def test_pass_fail_and_exempt(self):
        for status, recognized, earned in [("P", False, "3.000000"), ("F", False, "0.000000"), ("exempt", False, "0.000000"), ("exempt", True, "3.000000")]:
            with self.subTest(status=status, recognized=recognized):
                r = a.summary([dict(grade(None), status=status, recognized=recognized)])
                self.assertEqual(r["earned_credits"], earned)
                self.assertIsNone(r["cumulative_gpa"])

    def test_component_minimum(self):
        r = a.summary([grade("7", minimums_met=False)])
        self.assertEqual(r["earned_credits"], "0.000000")
        self.assertEqual(r["cumulative_gpa"], "2.800000")

    def test_required(self):
        self.assertEqual(a.required_gpa("213.12", "72", "3.2", "54")["required_future_gpa"], "3.520000")
        self.assertEqual(a.required_gpa("266.4", "90", "3.4", "54")["feasibility"], "impossible")

    def test_zero_credits(self):
        self.assertEqual(a.required_gpa("0", "0", "3.2", "18")["required_future_gpa"], "3.200000")
        self.assertEqual(a.required_gpa("0", "0", "3.2", "0")["feasibility"], "insufficient_data")
        self.assertEqual(a.required_gpa("12", "3", "3.2", "0")["feasibility"], "completed_target_met")

    def test_check_before_rounding(self):
        r = a.required_gpa("0.000001", "1", "2.000001", "1")
        self.assertEqual(r["feasibility"], "impossible")

    def test_target_score(self):
        parts = [dict(code=c, weight=w, score=s, minimum_required="0") for c,w,s in [("a",".1","9"),("b",".2","8"),("c",".3","7"),("final",".4",None)]]
        self.assertEqual(a.target_score(parts, "8", "final")["required_score"], "8.500000")
        parts[0]["score"] = None
        with self.assertRaisesRegex(ValueError, "MULTIPLE_UNKNOWN"):
            a.target_score(parts, "8", "final")

    def test_invalid_inputs(self):
        for invalid in ["NaN", "Infinity", "-1", "10.1", "1.0000001"]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                a.decimal(invalid, 0, 10)
