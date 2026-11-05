"""Application factory.

Run locally (from the repository root):
    uv run uvicorn sia.main:create_app --factory --reload

A factory (instead of a module-level `app` object) means nothing runs at import time, and
tests can build isolated apps with their own settings.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from sia import __version__
from sia.core.config import Settings, get_settings
from sia.core.db import create_engine, create_sessionmaker
from sia.core.errors import register_error_handlers
from sia.core.logging import configure_logging
from sia.core.middleware import (
    BodySizeLimitMiddleware,
    OriginCheckMiddleware,
    RequestContextMiddleware,
)
from sia.modules.companies.router import router as companies_router
from sia.modules.contacts.router import router as contacts_router
from sia.modules.enrichment.router import router as enrichment_router
from sia.modules.health.router import router as health_router
from sia.modules.identity.router import auth_router, org_router
from sia.modules.imports.router import router as imports_router
from sia.modules.insights.router import router as insights_router
from sia.modules.protection.rate_limit import RateLimitMiddleware
from sia.modules.scoring.router import router as scoring_router

logger = structlog.get_logger(__name__)

# Largest accepted request body: CSV uploads (5 MB) plus multipart overhead.
MAX_REQUEST_BYTES = 6 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        logger.info("app_started", env=settings.env, version=__version__)
        try:
            yield
        finally:
            await engine.dispose()
            logger.info("app_stopped")

    app = FastAPI(
        title="Sales Intelligence Agent API",
        version=__version__,
        lifespan=lifespan,
        # Interactive API docs are a development aid; don't publish the API map in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    register_error_handlers(app)
    # Middleware added last runs first: RequestContext wraps everything, so even requests
    # rejected by the origin check get a request ID and an access log line.
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(org_router)
    app.include_router(companies_router)
    app.include_router(contacts_router)
    app.include_router(imports_router)
    app.include_router(enrichment_router)
    app.include_router(scoring_router)
    app.include_router(insights_router)

    return app
