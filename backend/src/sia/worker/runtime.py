"""Database access for job code.

Jobs don't have an HTTP request or a logged-in session, so they say explicitly which tenant
they act for. `tenant_session()` re-applies that tenant context at the start of EVERY
transaction in the session (the context is transaction-local, see sia/core/tenancy.py), so a job
that commits part-way through can never continue without RLS context, or with another tenant's.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sia.core.config import Settings
from sia.core.db import create_engine, create_sessionmaker
from sia.core.tenancy import ORG_SETTING, USER_SETTING

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init(settings: Settings) -> None:
    global _engine, _sessionmaker
    _engine = create_engine(settings)
    _sessionmaker = create_sessionmaker(_engine)


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = _sessionmaker = None


@asynccontextmanager
async def tenant_session(
    *, organization_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Worker runtime not initialised: call sia.worker.runtime.init()")

    async with _sessionmaker() as session:

        @event.listens_for(session.sync_session, "after_begin")
        def _apply_tenant_context(_session: Any, _transaction: Any, connection: Any) -> None:
            connection.execute(
                text("SELECT set_config(:uk, :u, true), set_config(:ok, :o, true)"),
                {
                    "uk": USER_SETTING,
                    "u": str(user_id) if user_id else "",
                    "ok": ORG_SETTING,
                    "o": str(organization_id),
                },
            )

        yield session
