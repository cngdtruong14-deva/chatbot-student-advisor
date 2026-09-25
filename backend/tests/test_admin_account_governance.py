"""Admin account/profile/assignment governance on a disposable database."""
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app import api
from app.store import engine, one, rows, run
from app.test_safety import require_test_environment


@unittest.skipUnless(os.environ.get("ADVISOR_TEST_DATABASE") == "1", "isolated disposable database only")
class AdminAccountGovernanceTests(unittest.TestCase):
    def setUp(self):
        require_test_environment()
        self.conn = engine().connect()
        self.addCleanup(self.conn.close)
        outer = self.conn.begin()
        self.addCleanup(outer.rollback)
        self.users = {}
        for role in ("admin", "advisor", "student", "student"):
            uid = uuid4()
            key = role if role != "student" or "student" not in self.users else "student2"
            run(self.conn, "INSERT INTO app.users(id,email,username,password_hash,role) VALUES(:u,:e,:n,'test-only',:r)",
                u=uid, e=f"{uid}@test.invalid", n=f"governance_{key}_{uid.hex[:6]}", r=role)
            self.users[key] = {"id": uid, "role": role}
        run(self.conn, "INSERT INTO app.onboarding_profiles(user_id,display_name,major,cohort) VALUES(:u,'Pilot HTTT','Hệ thống thông tin','K74')",
            u=self.users["student"]["id"])
        curriculum = one(self.conn, "SELECT id FROM app.curricula WHERE status='demo' ORDER BY code,version LIMIT 1")
        if curriculum:
            run(self.conn, "INSERT INTO app.cohorts(code,curriculum_id) VALUES(:code,:curriculum)",
                code=f"GOV-{uuid4().hex[:8]}", curriculum=curriculum["id"])
        self.user = self.users["admin"]

        @contextmanager
        def isolated():
            with self.conn.begin_nested():
                yield self.conn

        for name in ("app.pilot_accounts.transaction", "app.api.transaction"):
            p = patch(name, isolated)
            p.start()
            self.addCleanup(p.stop)
        overrides = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(overrides)))
        app.dependency_overrides[api.actor] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def catalog(self):
        cohort = one(self.conn, """SELECT ch.id,ch.code,ch.curriculum_id FROM app.cohorts ch
            JOIN app.curricula c ON c.id=ch.curriculum_id WHERE c.status='demo' ORDER BY c.code,ch.code LIMIT 1""")
        if not cohort:
            self.skipTest("No reviewed curriculum/cohort fixture")
        return cohort

    def payload(self, code="GOV-001"):
        cohort = self.catalog()
        return {"student_code": code, "full_name": "Sinh viên kiểm thử",
                "curriculum_id": str(cohort["curriculum_id"]), "cohort_id": str(cohort["id"]),
                "confirmation": "LINK_ACADEMIC_PROFILE"}

    def test_admin_inventory_and_role_isolation(self):
        response = self.client.get("/api/v1/admin/accounts")
        self.assertEqual(response.status_code, 200, response.text)
        account = next(item for item in response.json()["data"]["items"]
                       if item["id"] == str(self.users["student"]["id"]))
        self.assertIsNone(account["student_id"])
        self.assertEqual(account["display_name"], "Pilot HTTT")
        self.assertEqual(account["personal_transcript_revision"], 0)
        self.assertGreater(len(self.client.get("/api/v1/admin/cohorts").json()["data"]["items"]), 0)

        for role in ("student", "advisor"):
            self.user = self.users[role]
            self.assertEqual(self.client.get("/api/v1/admin/accounts").status_code, 403)
            self.assertEqual(self.client.get("/api/v1/admin/account-audit").status_code, 403)

    def test_profile_link_is_idempotent_and_never_transfers_ownership(self):
        uid = self.users["student"]["id"]
        created = self.client.post(f"/api/v1/admin/accounts/{uid}/academic-profile", json=self.payload())
        self.assertEqual(created.status_code, 200, created.text)
        self.assertFalse(created.json()["data"]["idempotent"])
        student_id = created.json()["data"]["student_id"]

        replay = self.client.post(f"/api/v1/admin/accounts/{uid}/academic-profile", json=self.payload())
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["data"]["idempotent"])
        changed = self.client.post(f"/api/v1/admin/accounts/{uid}/academic-profile", json=self.payload("GOV-CHANGED"))
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "ACCOUNT_ALREADY_LINKED")

        other = self.users["student2"]["id"]
        claimed = self.client.post(f"/api/v1/admin/accounts/{other}/academic-profile", json=self.payload())
        self.assertEqual(claimed.status_code, 409)
        self.assertEqual(claimed.json()["error"]["code"], "STUDENT_CODE_ALREADY_LINKED")
        self.assertEqual(one(self.conn, "SELECT user_id FROM app.students WHERE id=:id", id=student_id)["user_id"], uid)
        self.assertEqual(one(self.conn, "SELECT count(*) AS n FROM app.account_audit WHERE action='academic_profile_linked'")["n"], 1)

    def test_assignment_visibility_and_revocation(self):
        uid = self.users["student"]["id"]
        student_id = self.client.post(f"/api/v1/admin/accounts/{uid}/academic-profile", json=self.payload()).json()["data"]["student_id"]
        body = {"advisor_user_id": str(self.users["advisor"]["id"]), "student_id": student_id}
        assigned = self.client.post("/api/v1/admin/advisor-assignments", json=body)
        self.assertEqual(assigned.status_code, 200, assigned.text)
        listing = self.client.get("/api/v1/admin/advisor-assignments").json()["data"]["items"]
        self.assertTrue(any(item["student_id"] == student_id for item in listing))

        self.user = self.users["advisor"]
        visible = self.client.get("/api/v1/advisor/students").json()["data"]["items"]
        self.assertEqual([item["id"] for item in visible], [student_id])
        self.assertEqual(self.client.post("/api/v1/admin/advisor-assignments", json=body).status_code, 403)

        self.user = self.users["admin"]
        removed = self.client.delete(f"/api/v1/admin/advisor-assignments/{body['advisor_user_id']}/{student_id}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(removed.json()["data"]["assigned"])
        self.user = self.users["advisor"]
        self.assertEqual(self.client.get("/api/v1/advisor/students").json()["data"]["items"], [])


if __name__ == "__main__":
    unittest.main()
