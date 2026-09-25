import os
import unittest
from unittest.mock import patch

from app.deployment_start import preflight


class DeploymentStartTests(unittest.TestCase):
    def test_smoke_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.deployment_start.grounded_smoke") as smoke:
            preflight()
        smoke.assert_not_called()

    def test_required_smoke_must_pass(self):
        with patch.dict(os.environ, {"RAG_DEPLOYMENT_GROUNDED_SMOKE_REQUIRED": "true"}, clear=True), \
                patch("app.deployment_start.grounded_smoke", return_value=0) as smoke:
            preflight()
        smoke.assert_called_once_with()

    def test_required_smoke_failure_stops_startup(self):
        with patch.dict(os.environ, {"RAG_DEPLOYMENT_GROUNDED_SMOKE_REQUIRED": "true"}, clear=True), \
                patch("app.deployment_start.grounded_smoke", return_value=1):
            with self.assertRaisesRegex(RuntimeError, "RAG_DEPLOYMENT_GROUNDED_SMOKE_FAILED"):
                preflight()


if __name__ == "__main__":
    unittest.main()
