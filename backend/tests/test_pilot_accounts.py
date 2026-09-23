"""Stage 2 validation tests; not a substitute for isolated database integration."""
import unittest
from pydantic import ValidationError
from app.pilot_accounts import Registration, PersonalProfile


class PilotInputTests(unittest.TestCase):
    def test_registration_rejects_role_or_student_id(self):
        data = dict(username="student_01", password="a-long-test-password", invite_code="x" * 32)
        for key in ("role", "student_id"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                Registration(**data, **{key: "admin"})

    def test_username_does_not_overlap_legacy_email(self):
        with self.assertRaises(ValidationError):
            Registration(username="user@example.com", password="a-long-test-password", invite_code="x" * 32)

    def test_blank_name_rejected(self):
        with self.assertRaises(ValidationError):
            PersonalProfile(display_name="   ")

    def test_profile_cannot_select_owner(self):
        with self.assertRaises(ValidationError):
            PersonalProfile(display_name="Student", user_id="someone-else")
