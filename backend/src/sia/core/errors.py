"""Error handling: one consistent JSON shape for every error response.

    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": [...]}}

- `code` is stable and machine-readable (clients branch on it); `message` is for humans.
- Internal details (stack traces, SQL, file paths) are never sent to clients — they are logged
  server-side, correlated by `request_id`.

Business logic raises `AppError` subclasses; it never builds HTTP responses itself.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for expected, client-facing errors."""

    status_code: ClassVar[int] = 400
    code: ClassVar[str] = "bad_request"

    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UnauthorizedError(AppError):
    """Not authenticated (missing, invalid or expired credentials)."""

    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    """Authenticated, but not allowed to do this."""

    status_code = 403
    code = "forbidden"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return value if isinstance(value, str) else None


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": current_request_id(),
    }
    if details:
        body["details"] = details
    return JSONResponse(
        status_code=status_code, content=jsonable_encoder({"error": body}), headers=headers
    )


# Codes for framework-raised HTTP errors (unknown route, wrong method, ...).
_HTTP_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    429: "rate_limited",
}


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # handler registered for this type only
        raise exc
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # handler registered for this type only
        raise exc
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # handler registered for this type only
        raise exc
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Request validation failed.", details)


def register_error_handlers(app: FastAPI) -> None:
    """Unhandled exceptions are converted to 500s by `RequestContextMiddleware` instead, so
    they are logged with full context and still carry the request ID."""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
