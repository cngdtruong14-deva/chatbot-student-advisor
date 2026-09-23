"""Code-level acceptance tests for the Stage 7 research-only importer."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest

from app.import_academic_demo_v2_research import validate_release


SCHEMA = Path("/contracts/academic_demo_v2_risk_day28.schema.json")


def record(index: int) -> dict:
    return {
        "case_id": f"AD2-{index:04d}",
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
            "published_assessment_mean_0_28": 7.0,
            "lms_active_days_0_28": 10,
        },
    }


class Stage7ResearchImportTests(unittest.TestCase):
    def test_requires_exactly_1000_synthetic_domain_records(self):
        records = [record(index) for index in range(1000)]
        validated = validate_release(records, SCHEMA)
        self.assertEqual(len(validated), 1000)
        self.assertEqual(len({digest for _, digest in validated}), 1000)

    def test_rejects_domain_relabel_and_duplicate_case(self):
        records = [record(index) for index in range(1000)]
        records[0]["domain_id"] = "oulad"
        with self.assertRaisesRegex(ValueError, "RESEARCH_DOMAIN_ORIGIN_MISMATCH"):
            validate_release(records, SCHEMA)
        records = [record(index) for index in range(1000)]
        records[-1] = copy.deepcopy(records[0])
        with self.assertRaisesRegex(ValueError, "RESEARCH_CASE_KEY_INVALID_OR_DUPLICATE"):
            validate_release(records, SCHEMA)


    def test_dashboard_endpoint_access_and_isolation(self):
        import os
        from uuid import uuid4
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api import actor

        client = TestClient(app)
        res_unauth = client.get("/api/v1/admin/research/dashboard")
        self.assertEqual(res_unauth.status_code, 401)

        student_user = {"id": str(uuid4()), "role": "student", "email": "student@demo.local"}
        advisor_user = {"id": str(uuid4()), "role": "advisor", "email": "advisor@demo.local"}
        admin_user = {"id": str(uuid4()), "role": "admin", "email": "admin@demo.local"}

        try:
            app.dependency_overrides[actor] = lambda: student_user
            res_student = client.get("/api/v1/admin/research/dashboard")
            self.assertEqual(res_student.status_code, 403)

            app.dependency_overrides[actor] = lambda: advisor_user
            res_advisor = client.get("/api/v1/admin/research/dashboard")
            self.assertEqual(res_advisor.status_code, 403)

            if os.environ.get("ADVISOR_TEST_DATABASE") == "1":
                app.dependency_overrides[actor] = lambda: admin_user
                res_admin = client.get("/api/v1/admin/research/dashboard")
                self.assertEqual(res_admin.status_code, 200)
                data = res_admin.json()["data"]
                self.assertEqual(data["domain_id"], "academic_demo_v2")
                self.assertEqual(data["data_origin"], "synthetic")
                self.assertEqual(data["expected_case_count"], 1000)
                self.assertIn("coverage_status", data)
                self.assertIn("limitations", data)
                raw_lower = res_admin.text.lower()
                for pat in ("student_id", "student_code", "sv0", "full_name", "transcript", "gpa_10", "cumulative_gpa"):
                    self.assertNotIn(pat, raw_lower)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
