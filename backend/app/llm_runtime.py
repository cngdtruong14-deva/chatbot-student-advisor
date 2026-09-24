"""Provider-neutral, citation-constrained generation over already retrieved evidence."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass

import httpx

# Keep the provider request small enough for a serverless Gemini gateway. The
# citation allow-list is still built from exactly the evidence sent below.
MAX_PROMPT_EVIDENCE_CHARS = 10_000
MAX_ANSWER_CHARS = 4_000
MAX_CLAIMS = 12
MAX_OUTPUT_TOKENS = 1200
MAX_RETRY_OUTPUT_TOKENS = 2000
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là bộ tổng hợp bằng chứng học vụ. Chỉ dùng thông tin trong EVIDENCE. "
    "Không bịa quy định, số liệu, ngày tháng. Không tự tính GPA.\n\n"
    "BƯỚC 1 — Đọc QUESTION.\n"
    "BƯỚC 2 — Tìm trong EVIDENCE các thông tin quy định về câu hỏi (bao gồm điều kiện, đối tượng, tiêu chuẩn, ngoại lệ, thủ tục).\n"
    "BƯỚC 3 — Quyết định:\n"
    "  • Nếu EVIDENCE có quy định hoặc tiêu chuẩn giải đáp câu hỏi: tổng hợp answer bám sát văn bản, gắn citation_id cho mỗi claim.\n"
    "  • Nếu QUESTION hỏi về việc áp dụng cho một năm học/ngày/khóa cụ thể (ví dụ: năm 1995, năm 2000, năm 2030) mà EVIDENCE không chứa năm/ngày đó: BẮT BUỘC trả {\"answer\":null,\"claims\":[]}. Không lấy năm/khóa khác để trả lời thay thế.\n"
    "  • Nếu EVIDENCE hoàn toàn không có thông tin giải đáp: trả {\"answer\":null,\"claims\":[]}.\n\n"
    "Output chỉ là JSON: {\"answer\":string|null,\"claims\":[{\"text\":string,\"citation_ids\":[string]}]}. "
    "Mỗi claim phải có citation_id từ EVIDENCE."
)


def prompt_sha256() -> str:
    """Return the exact prompt identity required by approval records."""
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def _clean_json_text(value: str) -> str:
    value = value.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else value


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    enabled: bool = False
    prompt_version: str = ""
    gateway_mode: bool = False
    rate_limit_retries: int = 1

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.model and self.api_key)


def config_from_env() -> ProviderConfig:
    try:
        # A failed provider should return the cited evidence promptly. Deployments
        # may raise this explicitly when their gateway has a slower SLA.
        timeout = min(max(float(os.environ.get("RAG_LLM_TIMEOUT_SECONDS", "12")), 5), 60)
    except ValueError:
        timeout = 12
    try:
        rate_limit_retries = min(max(int(os.environ.get("RAG_LLM_RATE_LIMIT_RETRIES", "1")), 0), 2)
    except ValueError:
        rate_limit_retries = 1
    provider = os.environ.get("RAG_LLM_PROVIDER", "").strip().lower()
    gemini = provider == "gemini"
    gateway_url = os.environ.get("RAG_LLM_GATEWAY_URL", "").strip().rstrip("/")
    gateway_secret = os.environ.get("RAG_LLM_GATEWAY_SECRET", "").strip()
    return ProviderConfig(
        # Gemini's documented OpenAI-compatible endpoint is used only when the
        # owner explicitly enables it and supplies a local model ID/key.
        base_url=(gateway_url or os.environ.get("RAG_LLM_BASE_URL", "").strip().rstrip("/") or
                  ("https://generativelanguage.googleapis.com/v1beta/openai" if gemini else "")),
        model=os.environ.get("RAG_LLM_MODEL", "").strip(),
        api_key=(gateway_secret if gateway_url else
                 (os.environ.get("GEMINI_API_KEY", "").strip() if gemini else os.environ.get("RAG_LLM_API_KEY", "").strip())),
        timeout_seconds=timeout,
        enabled=os.environ.get("RAG_LLM_ENABLED", "0").strip().lower() in {"1", "true", "yes"},
        prompt_version=os.environ.get("RAG_LLM_PROMPT_VERSION", "").strip(),
        gateway_mode=bool(gateway_url),
        rate_limit_retries=rate_limit_retries,
    )


def _signed_gateway_headers(secret: str, payload: bytes, timestamp: int | None = None) -> dict[str, str]:
    timestamp = int(time.time()) if timestamp is None else timestamp
    stamp = str(timestamp)
    signature = hmac.new(secret.encode("utf-8"), stamp.encode("ascii") + b"\n" + payload,
                         hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Gateway-Timestamp": stamp,
        "X-Gateway-Signature": signature,
    }


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig | None = None, transport=None):
        self.config = config or config_from_env()
        self.transport = transport
        self.last_usage = {}

    def status(self) -> str:
        return "configured" if self.config.configured else "provider_unavailable"

    def generate(self, question: str, matches: list[dict], *, prompt_version: str | None = None,
                 _abstention_retry: bool = False) -> dict:
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        result = self._generate(question, matches, prompt_version=prompt_version,
                                _abstention_retry=_abstention_retry, request_id=request_id,
                                deadline=started + self.config.timeout_seconds)
        logger.log(logging.INFO if result['status'] == 'completed' else logging.WARNING,
                   'rag_generation_result request_id=%s status=%s failure_reason=%s elapsed_ms=%d',
                   request_id, result['status'], result.get('failure_reason', 'none'),
                   round((time.monotonic() - started) * 1000))
        return result

    def _generate(self, question: str, matches: list[dict], *, prompt_version: str | None = None,
                  _abstention_retry: bool = False, request_id: str, deadline: float) -> dict:
        self.last_usage = {}
        if not self.config.configured:
            return {"status": "provider_unavailable", "answer": None, "claims": []}
        if prompt_version is not None and (not self.config.prompt_version or prompt_version != self.config.prompt_version):
            return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "PROMPT_VERSION_MISMATCH"}
        evidence, used = [], 0
        for item in matches:
            chunk = item["chunk"]
            excerpt = str(chunk["text"])
            remaining = MAX_PROMPT_EVIDENCE_CHARS - used
            if remaining <= 0:
                break
            excerpt = excerpt[:remaining]
            used += len(excerpt)
            evidence.append({"citation_id": chunk["chunk_id"], "title": chunk.get("title"), "section": chunk.get("section"), "text": excerpt})
        if not evidence:
            return {"status": "insufficient_evidence", "answer": None, "claims": []}
        allowed = {item["citation_id"] for item in evidence}
        body = {"model": self.config.model, "temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS,
                # Gemini's OpenAI-compatible endpoint accepts JSON-object mode.  The
                # prompt still defines the envelope and the validator below remains
                # authoritative for citations and abstentions.
                "response_format": {"type": "json_object"}, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "QUESTION:\n" + question + "\n\nEVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False)},
        ]}
        try:
            with httpx.Client(timeout=self.config.timeout_seconds, transport=self.transport) as client:
                response = None
                request_phase = 'not_started'
                for generation_attempt in range(2):
                    for rate_attempt in range(self.config.rate_limit_retries + 1):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise httpx.ReadTimeout('Generation budget exhausted')
                        payload_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        headers = (_signed_gateway_headers(self.config.api_key, payload_bytes)
                                   if self.config.gateway_mode
                                   else {"Authorization": "Bearer " + self.config.api_key,
                                         "Content-Type": "application/json"})
                        headers['X-Request-ID'] = request_id
                        attempt_started = time.monotonic()
                        request_phase = 'connect_or_gateway_queue'
                        with client.stream(
                            "POST", self.config.base_url + "/chat/completions",
                            headers=headers, content=payload_bytes, timeout=remaining,
                        ) as response:
                            headers_ms = round((time.monotonic() - attempt_started) * 1000)
                            request_phase = 'response_body'
                            response.read()
                            request_phase = 'response_complete'
                            total_ms = round((time.monotonic() - attempt_started) * 1000)
                        logger.info(
                            'rag_gateway_response request_id=%s http_status=%d headers_ms=%d total_ms=%d upstream_ms=%s response_bytes=%d',
                            request_id, response.status_code, headers_ms, total_ms,
                            response.headers.get('x-gateway-upstream-ms', 'unknown'),
                            len(response.content),
                        )
                        if response.status_code >= 400:
                            logger.warning('rag_generation_http request_id=%s http_status=%d generation_attempt=%d rate_attempt=%d',
                                           request_id, response.status_code, generation_attempt, rate_attempt)
                        if response.status_code == 429 and rate_attempt < self.config.rate_limit_retries:
                            delay = 2.0 * (rate_attempt + 1)
                            if deadline - time.monotonic() <= delay:
                                break
                            time.sleep(delay)
                            continue
                        break
                    if response.status_code >= 400:
                        break
                    payload = response.json()
                    choice = payload['choices'][0]
                    if choice.get('finish_reason') != 'length':
                        break
                    if generation_attempt == 0:
                        # A truncated JSON envelope is never accepted. Retry once with
                        # enough output room and an explicit concision instruction.
                        # The same evidence/citation allow-list remains in force.
                        body["max_tokens"] = MAX_RETRY_OUTPUT_TOKENS
                        body["messages"][0]["content"] = SYSTEM_PROMPT + (
                            "\nTrả lời súc tích; tối đa 6 claims và không lặp lại EVIDENCE."
                        )
                        continue
                    return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "OUTPUT_TRUNCATED"}
            if response is None:
                return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "NO_PROVIDER_RESPONSE"}
            if response.status_code in (401, 403):
                return {"status": "authentication_error", "answer": None, "claims": [], "failure_reason": "PROVIDER_AUTHENTICATION_FAILED"}
            if response.status_code == 429:
                return {"status": "rate_limited", "answer": None, "claims": [], "failure_reason": "PROVIDER_RATE_LIMITED"}
            if response.status_code in (408, 504):
                return {"status": "timeout", "answer": None, "claims": [], "failure_reason": "PROVIDER_HTTP_TIMEOUT"}
            if response.status_code >= 400:
                return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "PROVIDER_HTTP_ERROR"}
            payload = response.json()
            usage = payload.get('usage', {})
            if isinstance(usage, dict):
                self.last_usage = {k: usage[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if isinstance(usage.get(k),int)}
                logger.info('rag_generation_usage model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s',
                            self.config.model, usage.get('prompt_tokens'), usage.get('completion_tokens'), usage.get('total_tokens'))
            choice = payload['choices'][0]
            if choice.get('finish_reason') == 'length':
                return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "OUTPUT_TRUNCATED"}
            if choice.get('finish_reason') == 'content_filter':
                return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "CONTENT_FILTERED"}
            raw_content = (choice.get("message") or {}).get("content") or ""
            # OpenAI-compatible providers normally return a string, but some
            # gateways expose content parts.  Flatten text parts before parsing so
            # a valid JSON envelope is not rejected merely because of its wrapper.
            if isinstance(raw_content, list):
                raw_content = "".join(
                    part if isinstance(part, str) else str(part.get("text", ""))
                    for part in raw_content
                    if isinstance(part, (str, dict))
                )
            if not isinstance(raw_content, str):
                raw_content = ""
            if not raw_content.strip():
                # Gemini returned an empty body (e.g. safety filter silent refusal
                # or unsupported json_object mode). Treat as insufficient evidence.
                logger.warning("rag_generation_empty_content model=%s finish_reason=%s",
                               self.config.model, choice.get('finish_reason'))
                return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": "EMPTY_PROVIDER_CONTENT"}
            data = json.loads(_clean_json_text(raw_content))
            if not isinstance(data, dict):
                raise ValueError("INVALID_GENERATION_SCHEMA")
            answer, claims = data.get("answer"), data.get("claims")
            # A null answer is an abstention. Discard any explanatory claims;
            # they must never become factual output or cause a false provider failure.
            if 'answer' in data and answer is None and isinstance(claims, list):
                if not _abstention_retry:
                    # Gemini can occasionally emit a conservative null despite the
                    # same frozen evidence supporting a cited answer. Retry exactly
                    # once with the identical prompt/evidence. The second null still
                    # fails closed; no local answer is synthesized.
                    return self._generate(question, matches, prompt_version=prompt_version,
                                          _abstention_retry=True, request_id=request_id, deadline=deadline)
                return {"status": "insufficient_evidence", "answer": None, "claims": []}
            if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_ANSWER_CHARS or not isinstance(claims, list) or not claims or len(claims) > MAX_CLAIMS:
                raise ValueError("INVALID_GENERATION_SCHEMA")
            normalized = []
            for claim in claims:
                ids = claim.get("citation_ids") if isinstance(claim, dict) else None
                text = claim.get("text") if isinstance(claim, dict) else None
                if not isinstance(text, str) or not text.strip() or not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in allowed for i in ids):
                    raise ValueError("UNSUPPORTED_GENERATION_CITATION")
                normalized.append({"text": text.strip(), "citation_ids": list(dict.fromkeys(ids))})
            # Render only validated, cited claims. The provider's free-form answer may
            # contain extra unsupported prose even when its claims array looks valid.
            safe_answer = " ".join(claim["text"] for claim in normalized)
            if len(safe_answer) > MAX_ANSWER_CHARS:
                raise ValueError("GENERATED_CLAIMS_TOO_LARGE")
            return {"status": "completed", "answer": safe_answer, "claims": normalized, "usage": dict(self.last_usage)}
        except httpx.TimeoutException as exc:
            logger.warning('rag_generation_timeout request_id=%s exception_type=%s phase=%s',
                           request_id, type(exc).__name__,
                           locals().get('request_phase', 'provider_call'))
            return {"status": "timeout", "answer": None, "claims": [], "failure_reason": "PROVIDER_TIMEOUT"}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError, ValueError, json.JSONDecodeError) as exc:
            reason = "PROVIDER_RESPONSE_INVALID" if not isinstance(exc, httpx.HTTPError) else "PROVIDER_TRANSPORT_ERROR"
            logger.warning('rag_generation_invalid request_id=%s exception_type=%s validation_code=%s',
                           request_id, type(exc).__name__,
                           str(exc) if str(exc) in {'INVALID_GENERATION_SCHEMA', 'UNSUPPORTED_GENERATION_CITATION', 'GENERATED_CLAIMS_TOO_LARGE'} else 'REDACTED')
            return {"status": "provider_error", "answer": None, "claims": [], "failure_reason": reason}


def provider_status() -> str:
    return OpenAICompatibleProvider().status()
