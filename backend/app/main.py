import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.database import check_database
from app.api import APIError, Actor, envelope, router
from app import imports  # Register import endpoints before including the router.
from app import ai_runtime
from app import knowledge  # Register document endpoints before including router.
from app import pilot_accounts  # Additive pilot account endpoints.
from app import personal_academics  # Account-owned self-reported transcript.
from app import rag_feedback  # Bounded RAG evidence feedback; no provider access.
from app.production_security import (
    allowed_hosts,
    cors_origins,
    is_production,
    observability_headers,
    validate_production_environment,
)

validate_production_environment()

app = FastAPI(
    title="Student Advisor — Academic Demo v2",
    version="0.2.0",
    docs_url=None if is_production() else "/docs",
    redoc_url=None,
    openapi_url=None if is_production() else "/openapi.json",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
if cors_origins():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
app.include_router(router)


@app.exception_handler(APIError)
async def api_error(request, exc):
    data = envelope(None)
    data.pop("data")
    data["error"] = {"code": exc.code, "message": exc.message, "details": []}
    return JSONResponse(data, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return await api_error(request, APIError("INVALID_REQUEST", 422, "Dữ liệu không hợp lệ hoặc có trường ngoài hợp đồng"))


@app.exception_handler(ValueError)
async def domain_error(request, exc):
    codes = {"INVALID_GRADE", "INVALID_STATUS", "INVALID_CREDITS", "INVALID_WEIGHTS", "MULTIPLE_UNKNOWN_COMPONENTS", "INVALID_COMPONENT"}
    return await api_error(request, APIError(str(exc) if str(exc) in codes else "INVALID_REQUEST"))


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return await api_error(request, APIError("RESOURCE_NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR", exc.status_code))


@app.exception_handler(Exception)
async def unexpected(request, exc):
    logging.getLogger("advisor").error("Request failed: %s", type(exc).__name__)
    return await api_error(request, APIError("SERVICE_UNAVAILABLE", 503, "Dịch vụ tạm thời không sẵn sàng"))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'"
    )
    if is_production():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.middleware("http")(observability_headers)


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    try:
        return {"status": "ready", "database": "connected", "migration": check_database()}
    except Exception:
        return JSONResponse({"status": "not_ready", "database": "unavailable"}, status_code=503)


def capabilities():
    return {"stage": "academic_demo", "contract_version": "1.0.0", "features": {
        "authentication": "implemented_local", "gpa_and_what_if": "implemented_academic_demo_v2",
        **ai_runtime.capabilities(), "chat_tools": "deterministic_only"}}


@app.get("/api/v1/system/capabilities")
def system_capabilities(user: Actor):
    return envelope(capabilities())
