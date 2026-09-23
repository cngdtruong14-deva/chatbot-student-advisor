"""Operator opt-in for fixture writers; flags do not prove Docker isolation.

The operator must additionally inspect project/volume/network identity before
running a writer. Never set these flags from inside a test to bypass this guard.
"""
import os


def require_test_environment():
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("ADVISOR_TEST_DATABASE") != "1"
            or os.environ.get("RAG_LLM_ENABLED") != "0"):
        raise RuntimeError(
            "FIXTURE_WRITES_BLOCKED: require APP_ENV=test, "
            "ADVISOR_TEST_DATABASE=1, RAG_LLM_ENABLED=0 on a disposable stack"
        )
