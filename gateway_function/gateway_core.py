"""Pure validation and signing primitives for the stateless Gemini gateway."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from collections import deque
from threading import Lock

MAX_BODY_BYTES = 48_000
MAX_CLOCK_SKEW_SECONDS = 120
MAX_MESSAGES = 2
MAX_MESSAGE_CHARS = 30_000
MAX_OUTPUT_TOKENS = 2_000
UPSTREAM_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,80}")
_requests: deque[float] = deque()
_rate_lock = Lock()


class GatewayError(ValueError):
    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"MISSING_REQUIRED_CONFIGURATION:{name}")
    return value


def verify_signature(secret: str, timestamp: str | None, signature: str | None,
                     payload: bytes, now: int | None = None) -> None:
    try:
        stamp = int(timestamp or "")
    except ValueError as exc:
        raise GatewayError(401, "INVALID_GATEWAY_SIGNATURE") from exc
    current = int(time.time()) if now is None else now
    if abs(current - stamp) > MAX_CLOCK_SKEW_SECONDS:
        raise GatewayError(401, "EXPIRED_GATEWAY_SIGNATURE")
    expected = hmac.new(secret.encode(), str(stamp).encode("ascii") + b"\n" + payload,
                        hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature.lower()):
        raise GatewayError(401, "INVALID_GATEWAY_SIGNATURE")


def check_rate_limit() -> None:
    limit = min(max(int(os.environ.get("GATEWAY_REQUESTS_PER_MINUTE", "30")), 1), 300)
    now = time.monotonic()
    with _rate_lock:
        while _requests and now - _requests[0] >= 60:
            _requests.popleft()
        if len(_requests) >= limit:
            raise GatewayError(429, "GATEWAY_RATE_LIMITED")
        _requests.append(now)


def validate_envelope(body: object) -> dict:
    if not isinstance(body, dict) or set(body) - {"model", "temperature", "max_tokens", "messages", "response_format"}:
        raise GatewayError(400, "INVALID_GENERATION_ENVELOPE")
    if body.get("model") != required("GEMINI_MODEL") or body.get("temperature") != 0:
        raise GatewayError(400, "MODEL_OR_TEMPERATURE_NOT_ALLOWED")
    max_tokens = body.get("max_tokens")
    if not isinstance(max_tokens, int) or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
        raise GatewayError(400, "INVALID_OUTPUT_TOKEN_LIMIT")
    response_format = body.get("response_format")
    if response_format is not None and response_format != {"type": "json_object"}:
        raise GatewayError(400, "INVALID_RESPONSE_FORMAT")
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != MAX_MESSAGES:
        raise GatewayError(400, "INVALID_MESSAGE_SHAPE")
    if [item.get("role") if isinstance(item, dict) else None for item in messages] != ["system", "user"]:
        raise GatewayError(400, "INVALID_MESSAGE_ROLES")
    for item in messages:
        if set(item) != {"role", "content"} or not isinstance(item["content"], str):
            raise GatewayError(400, "INVALID_MESSAGE_SHAPE")
        if not item["content"] or len(item["content"]) > MAX_MESSAGE_CHARS:
            raise GatewayError(400, "INVALID_MESSAGE_SIZE")
    return body
