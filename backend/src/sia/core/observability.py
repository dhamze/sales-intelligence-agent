"""Error monitoring with Sentry (optional: nothing is sent unless SENTRY_DSN is set).

What is reported: every log event at ERROR level or above, with its traceback when there is
one. That covers crashes in API requests (logged by RequestContextMiddleware) and failed
background jobs (logged by the task code and by the job queue). The event name becomes the
Sentry message and the structured log context becomes searchable extra data.

What is NOT sent (privacy), enforced twice - by the SDK's `data_collection` settings and again
by `scrub_event` right before sending: user identity, cookies, request bodies, query strings,
all request headers except a few harmless ones, client IP addresses, AI prompts and responses
(the SDK instruments the Anthropic client automatically), database query parameters, local
variables in stack frames, and any context value whose key looks personal or secret.
"""

import logging
import re
import sys
from typing import Any, Literal

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from structlog.typing import EventDict, WrappedLogger

from sia import __version__
from sia.core.config import Settings

Component = Literal["api", "worker"]

_SAFE_HEADERS = {"user-agent", "content-type", "content-length", "x-request-id", "accept"}
_SENSITIVE_KEY = re.compile(r"email|ip|password|passwd|secret|token|cookie|auth|session|key", re.I)
_FILTERED = "[filtered]"
_STRUCTLOG_META = {"event", "level", "logger", "timestamp", "exc_info", "stack_info"}


def _scrub_mapping(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (_FILTERED if _SENSITIVE_KEY.search(k) else v) for k, v in values.items()}


def scrub_event(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remove personal and secret data from an event before it leaves the server."""
    request = event.get("request")
    if isinstance(request, dict):
        for field in ("cookies", "data", "query_string", "env"):
            request.pop(field, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: v for k, v in headers.items() if k.lower() in _SAFE_HEADERS}
    user = event.get("user")
    if isinstance(user, dict):
        user.pop("ip_address", None)
        user.pop("email", None)
    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _scrub_mapping(extra)
    return event


def init_sentry(settings: Settings, component: Component, *, transport: Any = None) -> bool:
    """Start Sentry for this process if a DSN is configured. Returns whether it started.
    `transport` lets tests capture events instead of sending them."""
    if settings.sentry_dsn is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.env,
        release=settings.release or f"sia@{__version__}",
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {"request": {"mode": "allowlist", "terms": sorted(_SAFE_HEADERS)}},
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "gen_ai": {"inputs": False, "outputs": False},  # prompts hold customer data
            "database_query_data": False,
            "stack_frame_variables": False,  # locals can hold page text or passwords
        },
        max_request_body_size="never",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=scrub_event,  # type: ignore[arg-type]
        # Standard-library log records become breadcrumbs only; events come from
        # `forward_errors_to_sentry` (cleaner messages, same scrubbing).
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        transport=transport,
    )
    sentry_sdk.set_tag("component", component)
    return True


def forward_errors_to_sentry(
    _logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor: send ERROR/CRITICAL log events to Sentry (if it's running)."""
    if method_name not in ("error", "exception", "critical") or not sentry_sdk.is_initialized():
        return event_dict
    exc_info = event_dict.get("exc_info")
    if exc_info is True:
        exc_info = sys.exc_info()
    context = {k: v for k, v in event_dict.items() if k not in _STRUCTLOG_META}
    with sentry_sdk.new_scope() as scope:
        for key, value in _scrub_mapping(context).items():
            scope.set_extra(key, value)
        if logger_name := event_dict.get("logger"):
            scope.set_tag("logger", str(logger_name))
        if request_id := context.get("request_id"):
            scope.set_tag("request_id", str(request_id))
        if isinstance(exc_info, tuple) and exc_info[1] is not None:
            sentry_sdk.capture_exception(exc_info[1])
        else:
            sentry_sdk.capture_message(str(event_dict.get("event")), level="error")
    return event_dict
