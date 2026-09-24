"""Fail-closed production configuration and HTTP middleware helpers.

The local/demo environment remains easy to run.  Production mode is explicit
and refuses wildcard/localhost origins, weak JWT keys, or an empty host
allowlist before the application starts serving requests.
"""
from __future__ import annotations

import os
import re
import time
import logging
import ipaddress
from urllib.parse import urlsplit
from uuid import uuid4


def csv_env(name: str) -> list[str]:
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


def is_production() -> bool:
    return os.environ.get("APP_ENV", "development").strip().lower() == "production"


def allowed_hosts() -> list[str]:
    values = csv_env("ALLOWED_HOSTS")
    if values:
        return list(dict.fromkeys([*values, "127.0.0.1", "localhost"]))
    return ["localhost", "127.0.0.1", "testserver"]


def cors_origins() -> list[str]:
    return csv_env("CORS_ALLOWED_ORIGINS")


def validate_production_environment() -> None:
    if not is_production():
        return
    errors: list[str] = []
    hosts = csv_env("ALLOWED_HOSTS")
    origins = cors_origins()
    jwt_secret = os.environ.get("JWT_SECRET", "")
    trusted_proxy = os.environ.get("TRUSTED_PROXY_IPS", "").strip()
    if not hosts or any("*" in host or "/" in host or "://" in host for host in hosts):
        errors.append("ALLOWED_HOSTS must contain explicit hostnames")
    if any(host.lower() in {"localhost", "127.0.0.1", "::1"} for host in hosts):
        errors.append("production ALLOWED_HOSTS cannot expose a localhost hostname")
    if not origins:
        errors.append("CORS_ALLOWED_ORIGINS must contain at least one HTTPS origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            errors.append("CORS_ALLOWED_ORIGINS must contain origin-only HTTPS URLs")
            break
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            errors.append("production CORS origins cannot use localhost")
            break
    if len(jwt_secret) < 32 or jwt_secret.startswith("REPLACE_"):
        errors.append("JWT_SECRET must be a non-placeholder secret of at least 32 characters")
    try:
        if not trusted_proxy or trusted_proxy == "*":
            raise ValueError
        ipaddress.ip_address(trusted_proxy)
    except ValueError:
        errors.append("TRUSTED_PROXY_IPS must be one explicit proxy IP")
    if trusted_proxy != os.environ.get("WEB_PROXY_IP", "").strip():
        errors.append("TRUSTED_PROXY_IPS must equal WEB_PROXY_IP")
    if os.environ.get("ADVISOR_TEST_DATABASE"):
        errors.append("ADVISOR_TEST_DATABASE must not be set in production")
    if os.environ.get("RAG_LLM_ENABLED", "0") == "1":
        provider = os.environ.get("RAG_LLM_PROVIDER", "").strip().lower()
        gateway_url = os.environ.get("RAG_LLM_GATEWAY_URL", "").strip()
        gateway_secret = os.environ.get("RAG_LLM_GATEWAY_SECRET", "").strip()
        direct_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if provider != "gemini" or not ((gateway_url and gateway_secret) or direct_key):
            errors.append("enabled production generation requires provider=gemini and either gateway credentials or GEMINI_API_KEY")
        if gateway_url and (urlsplit(gateway_url).scheme != "https" or not urlsplit(gateway_url).netloc):
            errors.append("RAG_LLM_GATEWAY_URL must be an absolute HTTPS URL")
    if errors:
        raise RuntimeError("PRODUCTION_CONFIGURATION_INVALID: " + "; ".join(errors))


def request_id(value: str | None) -> str:
    if value and re.fullmatch(r"[A-Za-z0-9._-]{8,80}", value):
        return value
    return str(uuid4())


async def observability_headers(request, call_next):
    """Emit bounded metadata without logging request bodies, tokens or queries."""
    rid = request_id(request.headers.get("x-request-id"))
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = rid
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms}"
    route = request.scope.get("route")
    route_template = getattr(route, "path", "unmatched")
    logging.getLogger("advisor.access").info(
        "request_complete request_id=%s method=%s route=%s status=%s duration_ms=%s",
        rid,
        request.method,
        route_template,
        response.status_code,
        elapsed_ms,
    )
    return response
