import json
import unittest
from unittest.mock import patch
from app.main import capabilities, live, ready


class FoundationTests(unittest.TestCase):
    def test_live(self):
        self.assertEqual(live(), {"status": "alive"})

    @patch("app.main.check_database", return_value="0001_foundation")
    def test_ready(self, _):
        self.assertEqual(ready()["migration"], "0001_foundation")

    @patch("app.main.check_database", side_effect=RuntimeError("SECRET_PASSWORD"))
    def test_failure_redacted(self, _):
        response = ready()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SECRET_PASSWORD", response.body.decode())
        self.assertEqual(json.loads(response.body)["status"], "not_ready")

    @patch('app.ai_runtime.approved_bundle', return_value=None)
    def test_no_fake_model(self, _):
        self.assertEqual(capabilities()["features"]["risk_model"], "not_configured")


if __name__ == "__main__":
    unittest.main()
