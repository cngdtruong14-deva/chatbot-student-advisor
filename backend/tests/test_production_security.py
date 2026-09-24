import os
import unittest
from unittest.mock import patch

from app.production_security import request_id, validate_production_environment
from app.document_extract import DocumentExtractionError, validate_upload_metadata


class ProductionConfigurationTests(unittest.TestCase):
    valid = {
        "APP_ENV": "production",
        "ALLOWED_HOSTS": "advisor.example.edu.vn",
        "CORS_ALLOWED_ORIGINS": "https://advisor.example.edu.vn",
        "JWT_SECRET": "unit-test-only-secret-with-at-least-32-characters",
        "TRUSTED_PROXY_IPS": "172.30.0.2",
        "WEB_PROXY_IP": "172.30.0.2",
        "RAG_LLM_ENABLED": "0",
    }

    def test_explicit_production_configuration_is_valid(self):
        with patch.dict(os.environ, self.valid, clear=True):
            validate_production_environment()

    def test_production_rejects_wildcards_http_localhost_and_test_database(self):
        invalid = {
            **self.valid,
            "ALLOWED_HOSTS": "*",
            "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
            "ADVISOR_TEST_DATABASE": "1",
            "TRUSTED_PROXY_IPS": "*",
        }
        with patch.dict(os.environ, invalid, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PRODUCTION_CONFIGURATION_INVALID"):
                validate_production_environment()

    def test_enabled_generation_requires_configured_gemini(self):
        invalid = {**self.valid, "RAG_LLM_ENABLED": "1", "RAG_LLM_PROVIDER": "gemini"}
        with patch.dict(os.environ, invalid, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                validate_production_environment()

    def test_enabled_generation_accepts_https_gateway_without_direct_gemini_key(self):
        valid = {
            **self.valid,
            "RAG_LLM_ENABLED": "1",
            "RAG_LLM_PROVIDER": "gemini",
            "RAG_LLM_GATEWAY_URL": "https://gateway.example/v1",
            "RAG_LLM_GATEWAY_SECRET": "x" * 32,
        }
        with patch.dict(os.environ, valid, clear=True):
            validate_production_environment()

    def test_request_id_is_bounded(self):
        self.assertEqual(request_id("client-id_123456"), "client-id_123456")
        self.assertNotEqual(request_id("bad value"), "bad value")
        self.assertLessEqual(len(request_id("x" * 200)), 80)


class UploadMetadataTests(unittest.TestCase):
    def test_exact_extension_and_content_type_pair_is_allowed(self):
        validate_upload_metadata("policy.pdf", "application/pdf")
        validate_upload_metadata(
            "curriculum.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_mismatch_or_unsafe_name_is_rejected(self):
        with self.assertRaisesRegex(DocumentExtractionError, "CONTENT_TYPE_MISMATCH"):
            validate_upload_metadata("policy.pdf", "text/plain")
        with self.assertRaisesRegex(DocumentExtractionError, "INVALID_FILENAME"):
            validate_upload_metadata("../policy.pdf", "application/pdf")


if __name__ == "__main__":
    unittest.main()
