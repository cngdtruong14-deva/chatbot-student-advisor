import unittest
from pathlib import Path

from app import ai_runtime
from advisor_core.ml_boundary import ACADEMIC_DEMO_V2_FEATURE_ORDER, validate_features


class AIRuntimeTests(unittest.TestCase):
    def test_demo_rag_returns_synthetic_citations_and_no_generated_answer(self):
        result = ai_runtime.retrieve("Học lại tính điểm như thế nào?", "demo_academic", None)
        self.assertEqual(result["corpus_version"], "DEMO-1-r1")
        self.assertEqual(result["generation_status"], "provider_unavailable")
        self.assertIsNone(result["answer"])
        self.assertTrue(result["citations"])
        self.assertTrue(all(citation["data_origin"] == "synthetic" for citation in result["citations"]))

    def test_oulad_model_is_not_available_without_local_receipt(self):
        original = ai_runtime.ROOT
        try:
            from pathlib import Path
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                ai_runtime.ROOT = Path(directory)
                with self.assertRaisesRegex(ai_runtime.AIRuntimeError, "MODEL_NOT_READY"):
                    ai_runtime.predict({"domain_id": "oulad", "data_origin": "public_dataset", "features": {}})
        finally:
            ai_runtime.ROOT = original

    def test_academic_demo_v2_uses_its_own_synthetic_feature_contract(self):
        record = {
            "case_id": "academic-demo-v2-smoke-1",
            "domain_id": "academic_demo_v2",
            "data_origin": "synthetic",
            "feature_schema_id": "academic_demo_v2_risk_day28",
            "feature_schema_version": "1.0.0",
            "cutoff_day": 28,
            "source_completeness": {"event_generator_verified": True, "transcript_label_verified": True},
            "features": {
                "prior_gpa_4": 2.5,
                "prior_attempts": 1,
                "attendance_rate_0_28": 0.8,
                "missed_sessions_0_28": 2,
                "submission_rate_0_28": 0.75,
                "published_assessment_mean_0_28": 6.5,
                "lms_active_days_0_28": 18,
            },
        }
        schema = Path(__file__).resolve().parents[2] / "contracts" / "academic_demo_v2_risk_day28.schema.json"
        values = validate_features(record, schema)
        self.assertEqual(values, [record["features"][name] for name in ACADEMIC_DEMO_V2_FEATURE_ORDER])

    def test_academic_demo_v2_model_is_not_available_without_its_own_receipt(self):
        original = ai_runtime.ROOT
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                ai_runtime.ROOT = Path(directory)
                self.assertIsNone(ai_runtime.approved_bundle("academic_demo_v2"))
        finally:
            ai_runtime.ROOT = original
