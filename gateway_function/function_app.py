"""HTTP-triggered Gemini gateway for Azure Functions Flex Consumption."""
from __future__ import annotations

import json
import os

import azure.functions as func
import httpx

from gateway_core import GatewayError, MAX_BODY_BYTES, REQUEST_ID_RE, UPSTREAM_URL
from gateway_core import check_rate_limit, required, validate_envelope, verify_signature

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def response(status: int, payload: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload, ensure_ascii=False), status_code=status,
                             mimetype="application/json")


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
    request_id = req.headers.get("x-request-id")
    if request_id and REQUEST_ID_RE.fullmatch(request_id):
        headers["X-Request-ID"] = request_id
    timeout = min(max(float(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "25")), 1), 45)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.post(UPSTREAM_URL, headers=headers, json=envelope)
        try:
            result = upstream.json()
        except ValueError:
            return response(502, {"error": {"code": "INVALID_UPSTREAM_RESPONSE"}})
        return response(upstream.status_code, result)
    except httpx.TimeoutException:
        return response(504, {"error": {"code": "UPSTREAM_TIMEOUT"}})
    except httpx.HTTPError:
        return response(502, {"error": {"code": "UPSTREAM_TRANSPORT_ERROR"}})
