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
from sia.core.middleware import RequestContextMiddleware
from sia.modules.health.router import router as health_router

logger = structlog.get_logger(__name__)


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
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)

    return app
