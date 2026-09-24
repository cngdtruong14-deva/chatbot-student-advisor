"""HTTP-triggered Gemini gateway for Azure Functions Flex Consumption."""
from __future__ import annotations

import json
import os
import logging
import time
import uuid
import asyncio

import azure.functions as func
import httpx

from gateway_core import GatewayError, MAX_BODY_BYTES, REQUEST_ID_RE, UPSTREAM_URL
from gateway_core import compact_upstream_response, check_rate_limit, required, validate_envelope, verify_signature

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
logger = logging.getLogger(__name__)


def response(status: int, payload: dict, headers: dict[str, str] | None = None) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload, ensure_ascii=False), status_code=status,
                             mimetype="application/json", headers=headers)


@app.route(route="healthz", methods=["GET"])
def healthz(req: func.HttpRequest) -> func.HttpResponse:
    del req
    required("GEMINI_API_KEY"); required("GATEWAY_SHARED_SECRET"); required("GEMINI_MODEL")
    return response(200, {"status": "ok"})


@app.route(route="v1/chat/completions", methods=["POST"])
async def chat_completions(req: func.HttpRequest) -> func.HttpResponse:
    payload = req.get_body()
    try:
        if not payload or len(payload) > MAX_BODY_BYTES:
            raise GatewayError(413, "GATEWAY_PAYLOAD_TOO_LARGE")
        verify_signature(required("GATEWAY_SHARED_SECRET"), req.headers.get("x-gateway-timestamp"),
                         req.headers.get("x-gateway-signature"), payload)
        check_rate_limit()
        try:
            envelope = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GatewayError(400, "INVALID_JSON") from exc
        envelope = validate_envelope(envelope)
    except GatewayError as exc:
        return response(exc.status_code, {"error": {"code": exc.code}})
    headers = {"Authorization": "Bearer " + required("GEMINI_API_KEY"), "Content-Type": "application/json"}
    request_id = req.headers.get("x-request-id", "")
    if not REQUEST_ID_RE.fullmatch(request_id):
        request_id = uuid.uuid4().hex
    headers["X-Request-ID"] = request_id
    timeout = min(max(float(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "25")), 1), 45)
    started = time.monotonic()
    try:
        # Include client setup, connection and response in one wall-clock budget.
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                upstream = await client.post(UPSTREAM_URL, headers=headers, json=envelope)
        upstream_ms = round((time.monotonic() - started) * 1000)
        logger.log(logging.WARNING if upstream.status_code >= 400 else logging.INFO,
                   'gemini_upstream request_id=%s http_status=%d elapsed_ms=%d response_bytes=%d',
                   request_id, upstream.status_code, upstream_ms, len(upstream.content))
        try:
            result = upstream.json()
        except ValueError:
            logger.warning('gemini_upstream_invalid_json request_id=%s http_status=%d',
                           request_id, upstream.status_code)
            return response(502, {"error": {"code": "INVALID_UPSTREAM_RESPONSE"}}, {
                "Cache-Control": "no-store", "X-Gateway-Request-ID": request_id,
                "X-Gateway-Upstream-Ms": str(upstream_ms),
            })
        if upstream.status_code < 400:
            try:
                result = compact_upstream_response(result)
            except GatewayError as exc:
                logger.warning('gemini_upstream_invalid_shape request_id=%s error_code=%s',
                               request_id, exc.code)
                return response(exc.status_code, {"error": {"code": exc.code}}, {
                    "Cache-Control": "no-store", "X-Gateway-Request-ID": request_id,
                    "X-Gateway-Upstream-Ms": str(upstream_ms),
                })
        return response(upstream.status_code, result, {
            "Cache-Control": "no-store",
            "X-Gateway-Request-ID": request_id,
            "X-Gateway-Upstream-Ms": str(upstream_ms),
        })
    except (httpx.TimeoutException, TimeoutError) as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.warning('gemini_upstream_timeout request_id=%s exception_type=%s elapsed_ms=%d timeout_seconds=%s',
                       request_id, type(exc).__name__, elapsed_ms, timeout)
        return response(504, {"error": {"code": "UPSTREAM_TIMEOUT"}}, {
            "Cache-Control": "no-store", "X-Gateway-Request-ID": request_id,
            "X-Gateway-Upstream-Ms": str(elapsed_ms),
        })
    except httpx.HTTPError as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.warning('gemini_upstream_transport request_id=%s exception_type=%s elapsed_ms=%d',
                       request_id, type(exc).__name__, elapsed_ms)
        return response(502, {"error": {"code": "UPSTREAM_TRANSPORT_ERROR"}}, {
            "Cache-Control": "no-store", "X-Gateway-Request-ID": request_id,
            "X-Gateway-Upstream-Ms": str(elapsed_ms),
        })
