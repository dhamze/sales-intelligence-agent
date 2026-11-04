"""Health endpoints, used by Docker, load balancers and deploy platforms.

- `/health/live`  — "is the process running?" Never touches dependencies, so a database outage
  does not cause the platform to restart healthy API processes in a loop.
- `/health/ready` — "can this instance serve traffic?" Checks the database. Returns 503 when a
  dependency is down, so traffic is routed elsewhere until it recovers.
"""

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.db import ping

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)

READINESS_TIMEOUT_SECONDS = 2.0

CheckStatus = Literal["ok", "unavailable"]


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus]


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    engine: AsyncEngine = request.app.state.engine
    database: CheckStatus = "ok"
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await ping(engine)
    except Exception as exc:
        # Log the real cause server-side; the response reveals nothing about infrastructure.
        logger.warning("readiness_check_failed", check="database", error=repr(exc))
        database = "unavailable"

    overall: CheckStatus = "ok" if database == "ok" else "unavailable"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status=overall, checks={"database": database})
