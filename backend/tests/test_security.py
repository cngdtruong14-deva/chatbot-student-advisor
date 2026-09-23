import os
import unittest
from unittest.mock import patch
from app.security import password_hash, verify_password, access_token, decode_token
from fastapi.testclient import TestClient
from app.main import app


class SecurityTests(unittest.TestCase):
    def test_password_hash_and_verification(self):
        password = "synthetic-test-password-only"
        encoded = password_hash(password)
        self.assertNotIn(password, encoded)
        self.assertTrue(verify_password(password, encoded))
        self.assertFalse(verify_password("wrong", encoded))

    @patch.dict(os.environ, {"JWT_SECRET": "synthetic-unit-test-key-32-bytes-minimum"})
    def test_jwt_sub_and_tampering(self):
        token = access_token("test-user-id")
        self.assertEqual(decode_token(token)["sub"], "test-user-id")
        with self.assertRaises(Exception):
            decode_token(token + "corrupt")

    def test_unauthenticated_routes_and_no_secret_echo(self):
        client = TestClient(app)
        for path in ["/api/v1/students/me", "/api/v1/system/capabilities", "/api/v1/research-cases"]:
            self.assertEqual(client.get(path).status_code, 401)
        response = client.post("/api/v1/auth/login", json={"email":"a", "password":"DO_NOT_ECHO", "unexpected":True})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("DO_NOT_ECHO", response.text)
