"""Database access: engine, sessions, and the declarative base for ORM models.

- One `AsyncEngine` (a connection pool) per process, created at app startup, disposed at
  shutdown.
- One `AsyncSession` per request, provided via FastAPI dependency injection (`DbSession`).
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from sia.core.config import Settings

# Deterministic constraint names. Without this, Postgres generates names that differ between
# databases, and Alembic cannot reliably drop or alter constraints in later migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,  # transparently replace connections the server has closed
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "server_settings": {"application_name": f"sia-api-{settings.env}"},
        },
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay usable after commit (needed when building
    # API responses from them in async code).
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping(engine: AsyncEngine) -> None:
    """Raise if the database cannot execute a trivial query."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(_get_session)]
