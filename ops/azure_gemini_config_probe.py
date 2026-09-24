"""Probe Gemini connectivity with synthetic text only; never sends corpus content."""
from __future__ import annotations

import json
import os

import httpx


def main() -> None:
    key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("RAG_LLM_MODEL", "")
    if not key or not model:
        raise SystemExit("GEMINI_CONFIGURATION_MISSING")
    response = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        headers={
            "Authorization": "Bearer " + key,
            "User-Agent": "chatbot-student-advisor/1.0 (+https://cngdtruong.id.vn)",
        },
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": 64,
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": "Return exactly: {\"ok\":true}"},
            ],
        },
        timeout=30,
    )
    result = {"model": model, "http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        result["error_type"] = type(error).__name__
        result["error_status"] = error.get("status") if isinstance(error, dict) else None
        result["error_message"] = (
            str(error.get("message", ""))[:500]
            if isinstance(error, dict)
            else str(error)[:500]
        )
        result["payload_keys"] = sorted(payload) if isinstance(payload, dict) else []
        result["content_type"] = response.headers.get("content-type")
        result["body_preview"] = response.text[:500]
    else:
        choice = (payload.get("choices") or [{}])[0]
        result["finish_reason"] = choice.get("finish_reason")
        result["content_present"] = bool((choice.get("message") or {}).get("content"))
    print(json.dumps(result, ensure_ascii=False))
    if response.status_code >= 400:
        raise SystemExit("GEMINI_CONFIG_PROBE_FAILED")


if __name__ == "__main__":
    main()
