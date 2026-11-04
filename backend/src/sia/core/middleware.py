"""Request context middleware.

For every HTTP request it:
1. Assigns a request ID (reusing a well-formed `X-Request-ID` from the caller, e.g. a load
   balancer, otherwise generating one) and returns it in the `X-Request-ID` response header.
2. Binds the ID to the logging context, so every log line written while handling the request
   includes it.
3. Logs one summary line per request: method, path, status, duration.
4. Converts any unhandled exception into a generic 500 JSON response, logging the full
   traceback server-side only.

Written as a plain ASGI middleware (rather than Starlette's `BaseHTTPMiddleware`) because it is
faster and does not interfere with streaming responses or context variables.
"""

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sia.core.errors import error_response

logger = structlog.get_logger("sia.request")

REQUEST_ID_HEADER = "x-request-id"
# Accept caller-supplied IDs only if short and plain, so they cannot inject content into logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        started_at = time.perf_counter()
        response_started = False
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                logger.exception("unhandled_exception")
                if response_started:
                    raise  # too late to send an error response; let the server close it
                response = error_response(500, "internal_error", "An unexpected error occurred.")
                await response(scope, receive, send_with_request_id)
            finally:
                logger.info(
                    "request_completed",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
                )
