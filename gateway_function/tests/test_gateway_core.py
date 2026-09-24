import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch

from gateway_function.gateway_core import GatewayError, validate_envelope, verify_signature


class GeminiGatewayTests(unittest.TestCase):
    def envelope(self):
        return {
            "model": "fixture-model",
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "bounded system"},
                {"role": "user", "content": "QUESTION: synthetic\nEVIDENCE: []"},
            ],
        }

    def test_valid_signature_and_envelope(self):
        payload = json.dumps(self.envelope(), separators=(",", ":")).encode()
        stamp = int(time.time())
        signature = hmac.new(
            b"fixture-secret", str(stamp).encode() + b"\n" + payload, hashlib.sha256
        ).hexdigest()
        verify_signature("fixture-secret", str(stamp), signature, payload, now=stamp)
        with patch.dict(os.environ, {"GEMINI_MODEL": "fixture-model"}, clear=False):
            self.assertEqual(validate_envelope(self.envelope())["model"], "fixture-model")

    def test_signature_rejects_tampering_and_expiry(self):
        payload = b"{}"
        stamp = 1000
        signature = hmac.new(
            b"fixture-secret", b"1000\n" + payload, hashlib.sha256
        ).hexdigest()
        with self.assertRaises(GatewayError) as expired:
            verify_signature("fixture-secret", str(stamp), signature, payload, now=1201)
        self.assertEqual(expired.exception.status_code, 401)
        with self.assertRaises(GatewayError) as tampered:
            verify_signature("fixture-secret", str(stamp), signature, b'{"x":1}', now=stamp)
        self.assertEqual(tampered.exception.status_code, 401)

    def test_envelope_rejects_unknown_model_roles_and_limits(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": "fixture-model"}, clear=False):
            cases = []
            wrong_model = self.envelope()
            wrong_model["model"] = "other"
            cases.append(wrong_model)
            wrong_role = self.envelope()
            wrong_role["messages"][1]["role"] = "assistant"
            cases.append(wrong_role)
            too_many = self.envelope()
            too_many["max_tokens"] = 2001
            cases.append(too_many)
            extra = self.envelope()
            extra["stream"] = True
            cases.append(extra)
            invalid_format = self.envelope()
            invalid_format["response_format"] = {"type": "json_schema"}
            cases.append(invalid_format)
            for value in cases:
                with self.subTest(value=value), self.assertRaises(GatewayError):
                    validate_envelope(value)


if __name__ == "__main__":
    unittest.main()
