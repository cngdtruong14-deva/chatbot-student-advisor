import unittest
import os
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.knowledge import resolve_actor_scope
from app.security import access_token, password_hash
from app.store import transaction, one, run


@unittest.skipUnless(os.environ.get('ADVISOR_TEST_DATABASE') == '1', 'isolated disposable database only')
class CatalogImportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _admin_token(self):
        with transaction() as db:
            admin_user = one(db, "SELECT * FROM app.users WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
            if not admin_user:
                self.skipTest("No admin user in database")
            return access_token(admin_user["id"])

    def _student_token(self):
        with transaction() as db:
            student = one(db, "SELECT * FROM app.users WHERE role='student' AND is_active ORDER BY created_at LIMIT 1")
            if not student:
                self.skipTest("No student user in database")
            return access_token(student["id"])

    def test_httt_catalog_and_profile_selection(self):
        student_headers = {"Authorization": f"Bearer {self._student_token()}"}
        response = self.client.get("/api/v1/catalog/curricula", headers=student_headers)
        self.assertEqual(response.status_code, 200, response.text)
        htt = next(item for item in response.json()["data"]["items"] if item["code"] == "HTTT-UTT")
        self.assertEqual(htt["major"], "Hệ thống thông tin")
        self.assertEqual(htt["faculty"], "Công nghệ thông tin")
        self.assertEqual(htt["total_required_credits"], "157.000000")
        cohorts = self.client.get("/api/v1/catalog/cohorts", headers=student_headers)
        self.assertEqual(cohorts.status_code, 200, cohorts.text)
        self.assertTrue(any(item["code"] == "K75" and item["curriculum_id"] == htt["id"]
                            for item in cohorts.json()["data"]["items"]))
        with transaction() as db:
            counts = one(db, """SELECT count(*) AS total,
                    count(*) FILTER (WHERE cc.required) AS required,
                    count(*) FILTER (WHERE NOT cc.required) AS elective,
                    count(*) FILTER (WHERE cc.recommended_term_no IS NOT NULL) AS invented_terms,
                    count(*) FILTER (WHERE NOT cc.counts_for_gpa) AS non_gpa
                FROM app.curriculum_courses cc JOIN app.curricula c ON c.id=cc.curriculum_id
                WHERE c.code='HTTT-UTT' AND c.version='2024'""")
            prerequisites = one(db, """SELECT count(*) AS total FROM app.prerequisites p
                JOIN app.curricula c ON c.id=p.curriculum_id
                WHERE c.code='HTTT-UTT' AND c.version='2024'""")
        self.assertEqual((counts["total"], counts["required"], counts["elective"],
                          counts["invented_terms"], counts["non_gpa"]), (72, 53, 19, 0, 8))
        self.assertEqual(prerequisites["total"], 45)
        bad = self.client.put("/api/v1/account/profile", headers=student_headers,
            json={"display_name": "Pilot", "major": "Ngành không tồn tại", "cohort": "K75"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["code"], "UNKNOWN_MAJOR")
        wrong_cohort = self.client.put("/api/v1/account/profile", headers=student_headers,
            json={"display_name": "Pilot", "major": "Hệ thống thông tin", "cohort": "K74"})
        self.assertEqual(wrong_cohort.status_code, 422)
        self.assertEqual(wrong_cohort.json()["error"]["code"], "UNKNOWN_COHORT")
        good = self.client.put("/api/v1/account/profile", headers=student_headers,
            json={"display_name": "Pilot", "major": "Hệ thống thông tin", "cohort": "K75"})
        self.assertEqual(good.status_code, 200, good.text)
        denied = self.client.get("/api/v1/admin/majors", headers=student_headers)
        self.assertEqual(denied.status_code, 403)

    def test_unlinked_account_keeps_general_rag_scope_until_academic_link(self):
        with transaction() as db:
            user = one(db, """SELECT u.* FROM app.users u WHERE u.role='student' AND u.is_active
                AND NOT EXISTS(SELECT 1 FROM app.students s WHERE s.user_id=u.id)
                ORDER BY u.created_at LIMIT 1""")
        if not user:
            self.skipTest("No unlinked pilot account in fixture")
        headers = {"Authorization": f"Bearer {access_token(user['id'])}"}
        saved = self.client.put("/api/v1/account/profile", headers=headers,
            json={"display_name": "Pilot HTTT", "major": "Hệ thống thông tin", "cohort": "K75"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(resolve_actor_scope({"id": user["id"], "role": "student"}),
                         {"major": "all", "cohort": "all", "resolved": False})

    def test_courses_import_dry_run_and_commit(self):
        token = self._admin_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/csv"}

        csv_content = f"code,title\nTEST_CS_{uuid4().hex[:6]},Kiem thu phan mem\n"

        # 1. Dry run
        res = self.client.post("/api/v1/admin/imports/courses?dry_run=true", headers=headers, content=csv_content.encode())
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["status"], "validated")
        self.assertEqual(data["rows"], 1)

        # 2. Commit
        res2 = self.client.post("/api/v1/admin/imports/courses?dry_run=false", headers=headers, content=csv_content.encode())
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()["data"]
        self.assertEqual(data2["status"], "completed")
        self.assertEqual(data2["writes"], 1)

    def test_prerequisites_detects_cycle(self):
        token = self._admin_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/csv"}

        with transaction() as db:
            # The fixture must be deterministic once more than one curriculum
            # exists.  These import-contract tests exercise the seeded DEMO-CS
            # namespace, not whichever curriculum PostgreSQL happens to return
            # first.
            cur = one(db, "SELECT code FROM app.curricula WHERE code='DEMO-CS' AND version='1'")
            c1 = one(db, "SELECT code FROM app.courses WHERE domain_id='demo_academic' ORDER BY code LIMIT 1")
            c2 = one(db, "SELECT code FROM app.courses WHERE domain_id='demo_academic' AND code<>:c1 ORDER BY code LIMIT 1", c1=c1["code"])
            if not cur or not c1 or not c2:
                self.skipTest("Not enough courses/curricula")
            cur_code = cur["code"]
            c1_code = c1["code"]
            c2_code = c2["code"]

        # Cycle: c1 requires c2, AND c2 requires c1
        cycle_csv = f"curriculum_code,curriculum_version,course_code,prerequisite_course_code,min_grade_point\n{cur_code},1,{c1_code},{c2_code},1.6\n{cur_code},1,{c2_code},{c1_code},1.6\n"
        res = self.client.post("/api/v1/admin/imports/prerequisites?dry_run=true", headers=headers, content=cycle_csv.encode())
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["status"], "invalid")
        self.assertTrue(any(e.get("code") == "PREREQUISITE_CYCLE_DETECTED" for e in data["errors"]))

    def test_grade_components_weights_exceed_one(self):
        token = self._admin_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/csv"}

        with transaction() as db:
            offering = one(db, """SELECT c.code AS course, s.code AS semester FROM app.course_offerings o
              JOIN app.courses c ON c.id=o.course_id JOIN app.semesters s ON s.id=o.semester_id LIMIT 1""")
            if not offering:
                self.skipTest("No offering available")
            course_code = offering["course"]
            sem_code = offering["semester"]

        # 0.6 + 0.5 = 1.1 > 1.0
        bad_csv = f"course_code,semester_code,component_code,weight,minimum_required\n{course_code},{sem_code},GK,0.6,0\n{course_code},{sem_code},CK,0.5,3\n"
        res = self.client.post("/api/v1/admin/imports/grade_components?dry_run=true", headers=headers, content=bad_csv.encode())
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["status"], "invalid")
        self.assertTrue(any(e.get("code") == "ASSESSMENT_WEIGHTS_NOT_ONE" for e in data["errors"]))

    def test_students_import_dry_run_and_commit(self):
        token = self._admin_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/csv"}

        with transaction() as db:
            cur = one(db, "SELECT id,code FROM app.curricula WHERE code='DEMO-CS' AND version='1'")
            if not cur:
                self.skipTest("No curriculum available")
            cur_code = cur["code"]
            cohort_code = f"COHORT_{uuid4().hex[:6]}"
            run(db, "INSERT INTO app.cohorts(code,curriculum_id) VALUES(:code,:curriculum)", code=cohort_code, curriculum=cur["id"])

        suffix = uuid4().hex[:6]
        email = f"test_{suffix}@student.edu"
        with transaction() as db:
            run(db, "INSERT INTO app.users(email,password_hash,role) VALUES(:email,:hash,'student')", email=email, hash=password_hash("NotUsedByImport"))
        csv_content = f"student_code,full_name,account_email,cohort,curriculum_code,curriculum_version\nSTU_{suffix},Nguyen Van Test,{email},{cohort_code},{cur_code},1\n"

        # 1. Dry run
        res = self.client.post("/api/v1/admin/imports/students?dry_run=true", headers=headers, content=csv_content.encode())
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["status"], "validated")
        self.assertEqual(data["rows"], 1)

        # 2. Commit
        res2 = self.client.post("/api/v1/admin/imports/students?dry_run=false", headers=headers, content=csv_content.encode())
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()["data"]
        self.assertEqual(data2["status"], "completed")
        self.assertEqual(data2["writes"], 1)


if __name__ == "__main__":

    unittest.main()
