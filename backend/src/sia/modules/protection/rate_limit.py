"""Per-IP rate limiting, stored in PostgreSQL (ADR-0013).

Fixed windows: every request increments one counter per matching rule, in ONE statement, and is
refused with 429 + Retry-After once a counter passes its limit. Counters live in PostgreSQL so
they are shared by all API processes without running Redis; at this scale one indexed upsert
per request costs well under a millisecond.

Client IPs are hashed before storage (they are personal data and only need to be compared).
The client IP comes from uvicorn's proxy-header handling: behind Caddy it is the real client.
If the database is unreachable the request is let through (fail open): the API cannot serve it
without the database anyway, and blocking every request would turn a blip into an outage.

Expired counters are deleted by the requests themselves (about 1 in CLEANUP_EVERY), so the
table stays small without a scheduler.
"""

import hashlib
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp, Receive, Scope, Send

from sia.core.config import Settings
from sia.core.errors import error_response

logger = structlog.get_logger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EXEMPT_PREFIXES = ("/health/",)  # probes from Docker and uptime monitors
CLEANUP_EVERY = 500


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window_seconds: int
    matches: Callable[[str, str], bool]  # (method, path) -> applies?


def rules_for(settings: Settings) -> list[Rule]:
    return [
        Rule("all", settings.rate_limit_requests_per_minute, 60, lambda _m, _p: True),
        Rule(
            "writes",
            settings.rate_limit_writes_per_minute,
            60,
            lambda m, _p: m not in SAFE_METHODS,
        ),
        Rule(
            "signup",
            settings.rate_limit_signups_per_hour,
            3600,
            lambda m, p: m == "POST" and p == "/auth/signup",
        ),
    ]


def _client_key(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:32]


_HIT = text(
    """
    INSERT INTO rate_limit_hits (key, window_start, hits)
    SELECT k, to_timestamp(floor(extract(epoch FROM now()) / w) * w), 1
    FROM unnest(CAST(:keys AS text[]), CAST(:windows AS int[])) AS t(k, w)
    ON CONFLICT (key, window_start) DO UPDATE SET hits = rate_limit_hits.hits + 1
    RETURNING key, hits
    """
)
# Counters older than 2 hours can no longer affect any rule (the longest window is one hour).
_CLEANUP = text("DELETE FROM rate_limit_hits WHERE window_start < now() - interval '2 hours'")


async def hit(engine: AsyncEngine, ip: str, rules: list[Rule]) -> int | None:
    """Count one request; return seconds to wait if any limit is exceeded, else None."""
    client = _client_key(ip)
    keys = {f"{r.name}:{client}": r for r in rules}
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                _HIT, {"keys": list(keys), "windows": [r.window_seconds for r in rules]}
            )
        ).all()
        if random.randrange(CLEANUP_EVERY) == 0:  # noqa: S311 (not security-relevant)
            await conn.execute(_CLEANUP)
    now = time.time()
    waits = [
        math.ceil(keys[key].window_seconds - now % keys[key].window_seconds)
        for key, hits in rows
        if hits > keys[key].limit
    ]
    return max(waits) if waits else None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.rules = rules_for(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        engine: AsyncEngine | None = getattr(scope["app"].state, "engine", None)
        if client is None or engine is None:
            await self.app(scope, receive, send)
            return

        method, path = scope["method"], scope["path"]
        rules = [r for r in self.rules if r.matches(method, path)]
        try:
            wait = await hit(engine, client[0], rules)
        except Exception as exc:  # fail open (see module docstring)
            logger.warning("rate_limit_check_failed", error=repr(exc))
            wait = None
        if wait is not None:
            logger.warning("rate_limited", method=method, path=path, retry_after=wait)
            response = error_response(
                429, "rate_limited", "Too many requests. Please slow down and try again shortly."
            )
            response.headers["Retry-After"] = str(wait)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
