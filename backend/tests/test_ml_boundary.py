import unittest
from advisor_core.ml_boundary import build_features, validate_features


class BoundaryTests(unittest.TestCase):
    def fixture(self):
        return {"case_id": "fixture-only", "data_origin": "synthetic", "static": {
            "registration_day": -3, "withdrawal_day": None, "num_of_prev_attempts": 0, "studied_credits": 60},
            "vle": [{"day": 0, "sum_click": 2}, {"day": 28, "sum_click": 3}, {"day": 29, "sum_click": 900}],
            "assessments": [{"assessment_id": 1, "submitted_day": 28, "is_banked": False, "is_exam": False},
                            {"assessment_id": 1, "submitted_day": 28, "is_banked": False, "is_exam": False},
                            {"assessment_id": 2, "submitted_day": 29, "is_banked": False, "is_exam": False}]}

    def build(self, fixture):
        return build_features("oulad", fixture, 28, {"static_verified": True, "vle_complete": True, "assessment_complete": True})

    def test_cutoff_and_distinct_count(self):
        record = self.build(self.fixture())
        values = validate_features(record, "/contracts/oulad_features_v1.schema.json", allow_synthetic=True)
        self.assertEqual(values, [0, 60, 5, 2, 1, 0])
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_NOT_RESEARCH"):
            validate_features(record, "/contracts/oulad_features_v1.schema.json")

    def test_no_activity_null_not_zero(self):
        fixture = self.fixture()
        fixture["vle"] = []
        self.assertIsNone(self.build(fixture)["features"]["days_since_last_vle_activity"])

    def test_domain_and_population(self):
        with self.assertRaisesRegex(ValueError, "DOMAIN"):
            build_features("demo_academic", self.fixture(), 28, {})
        fixture = self.fixture()
        fixture["static"]["withdrawal_day"] = 28
        with self.assertRaisesRegex(ValueError, "POPULATION"):
            self.build(fixture)

    def test_missing_source_is_not_zero(self):
        with self.assertRaisesRegex(ValueError, "INSUFFICIENT"):
            build_features("oulad", self.fixture(), 28, {"static_verified": True})
