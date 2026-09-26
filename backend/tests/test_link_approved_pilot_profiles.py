"""Safety contract for the immutable production pilot-link batch."""
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

from app.link_approved_pilot_profiles import CONFIRMATION, apply_batch
from app.store import one, run


class ApprovedPilotProfileLinkTests(unittest.TestCase):
    profiles = [
        {"username": "pilot_alpha", "student_code": "PILOT-ALPHA", "full_name": "Pilot Alpha"},
        {"username": "pilot_beta", "student_code": "PILOT-BETA", "full_name": "Pilot Beta"},
    ]

    def setUp(self):
        self.users = {}
        self.curriculum_id = uuid4()
        self.cohort_id = uuid4()
        self.students = {}
        self.audits = []

        @contextmanager
        def fake_transaction():
            yield self

        def fake_one(_db, query, **params):
            if "FROM app.curricula" in query:
                return {"id": self.curriculum_id, "code": "HTTT-UTT", "version": "2024"}
            if "FROM app.cohorts" in query:
                return {"id": self.cohort_id, "code": "K75", "curriculum_id": self.curriculum_id}
            if "FROM app.users" in query:
                username = params["username"]
                return self.users.setdefault(username, {"id": uuid4(), "username": username,
                                                         "role": "student", "is_active": True})
            if "FROM app.students WHERE user_id" in query:
                return self.students.get(params["user_id"])
            if "FROM app.students" in query and "student_code" in params:
                return None
            if "INSERT INTO app.students" in query:
                student = {"id": uuid4(), "student_code": params["student_code"],
                           "curriculum_id": params["curriculum_id"], "cohort_id": params["cohort_id"]}
                self.students[params["user_id"]] = student
                return {"id": student["id"]}
            raise AssertionError(query)

        def fake_run(_db, query, **params):
            if "INSERT INTO app.account_audit" not in query:
                raise AssertionError(query)
            self.audits.append(params["subject_id"])

        patches = (
            patch("app.link_approved_pilot_profiles.transaction", fake_transaction),
            patch("app.link_approved_pilot_profiles.one", fake_one),
            patch("app.link_approved_pilot_profiles.run", fake_run),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_dry_run_is_read_only_and_lists_exact_reviewed_batch(self):
        result = apply_batch(self.profiles, dry_run=True)
        self.assertEqual([item["username"] for item in result["results"]],
                         ["pilot_alpha", "pilot_beta"])
        self.assertEqual({item["status"] for item in result["results"]}, {"would_link"})
        self.assertEqual(self.students, {})
        self.assertEqual(self.audits, [])

    def test_apply_is_atomic_audited_and_idempotent(self):
        result = apply_batch(self.profiles, confirmation=CONFIRMATION)
        self.assertEqual({item["status"] for item in result["results"]}, {"linked"})
        self.assertEqual(len(self.students), 2)
        self.assertEqual(len(self.audits), 2)
        replay = apply_batch(self.profiles, confirmation=CONFIRMATION)
        self.assertEqual({item["status"] for item in replay["results"]}, {"idempotent"})
        self.assertEqual(len(self.audits), 2)

    def test_confirmation_and_batch_are_closed(self):
        with self.assertRaisesRegex(ValueError, "CONFIRM_REQUIRED"):
            apply_batch(self.profiles)
        with self.assertRaisesRegex(ValueError, "PROFILE_IDENTIFIER_INVALID"):
            apply_batch([{"username": "pilot", "student_code": "REAL-001",
                          "full_name": "Not allowed"}], dry_run=True)


if __name__ == "__main__":
    unittest.main()
