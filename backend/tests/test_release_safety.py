"""Release 0-1 regression checks. No live requests or fixture writes.

Run inside the new API image, not against a running live HTTP endpoint.
Environment flags only express opt-in; operators still verify DB isolation.
"""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.test_safety import require_test_environment


class FixtureOptInTests(unittest.TestCase):
    allowed = {
        "APP_ENV": "test",
        "ADVISOR_TEST_DATABASE": "1",
        "RAG_LLM_ENABLED": "0",
    }

    def test_explicit_test_configuration_allowed(self):
        with patch.dict(os.environ, self.allowed, clear=True):
            require_test_environment()

    def test_each_missing_flag_rejected(self):
        for key in self.allowed:
            values = self.allowed.copy()
            del values[key]
            with self.subTest(missing=key), patch.dict(os.environ, values, clear=True):
                with self.assertRaisesRegex(RuntimeError, "FIXTURE_WRITES_BLOCKED"):
                    require_test_environment()

    def test_each_invalid_flag_rejected(self):
        invalid = {
            "APP_ENV": ("", "production", "staging", "TEST"),
            "ADVISOR_TEST_DATABASE": ("", "0", "true", " 1"),
            "RAG_LLM_ENABLED": ("", "1", "false", "0 "),
        }
        for key, candidates in invalid.items():
            for value in candidates:
                values = {**self.allowed, key: value}
                with self.subTest(key=key, value=value), patch.dict(os.environ, values, clear=True):
                    with self.assertRaisesRegex(RuntimeError, "FIXTURE_WRITES_BLOCKED"):
                        require_test_environment()

    def test_empty_environment_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FIXTURE_WRITES_BLOCKED"):
                require_test_environment()


class RemovedAuthBypassTests(unittest.TestCase):
    def test_bypass_not_registered_even_in_test_mode(self):
        self.assertFalse(any(
            getattr(route, "path", "").rstrip("/") == "/api/v1/auth/test-token"
            for route in app.routes
        ))

    def test_request_is_404_without_session_or_cookie(self):
        # A regressed route must never actually reach the database or issue().
        with patch("app.api.transaction", side_effect=AssertionError("Unexpected DB access")) as db, \
                patch("app.api.issue", side_effect=AssertionError("Unexpected token issuance")) as issue:
            with TestClient(app) as client:
                for suffix in ("", "/"):
                    response = client.post(
                        "/api/v1/auth/test-token" + suffix,
                        json={"email": "fixture-only@example.invalid"},
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertNotIn("set-cookie", response.headers)
                    self.assertNotIn("access_token", response.text)
                    self.assertEqual(response.json()["error"]["code"], "RESOURCE_NOT_FOUND")
            db.assert_not_called()
            issue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
