"""Background jobs: transactional enqueueing, tenant isolation inside jobs, retries.

The worker runs in-process against the real test database, as the restricted runtime role.
"""

import uuid
from collections.abc import AsyncIterator

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.config import APP_DB_ROLE, Settings
from sia.core.db import create_sessionmaker
from sia.core.jobs import enqueue
from sia.worker import app, configured_app, conninfo, runtime

QUEUE = "tests"


@app.task(name="tests.rename_company", queue=QUEUE)
async def rename_company(organization_id: str, company_id: str, name: str) -> None:
    async with runtime.tenant_session(organization_id=uuid.UUID(organization_id)) as db:
        # Two transactions: the tenant context must be re-applied after the first commit.
        first = await db.execute(
            text("UPDATE companies SET name = :n WHERE id = :id RETURNING id"),
            {"n": name, "id": company_id},
        )
        renamed = len(first.all())
        await db.commit()
        second = await db.execute(
            text("UPDATE companies SET city = 'Updated' WHERE id = :id RETURNING id"),
            {"id": company_id},
        )
        relocated = len(second.all())
        await db.commit()
    if renamed != 1 or relocated != 1:
        raise LookupError("company not visible to this tenant")


@app.task(
    name="tests.always_fails",
    queue=QUEUE,
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=0),  # 3 RETRIES after the first run
)
async def always_fails() -> None:
    raise RuntimeError("boom")


@pytest.fixture
async def worker(test_settings: Settings) -> AsyncIterator[procrastinate.App]:
    runtime.init(test_settings)
    configured = configured_app(test_settings)
    async with configured.open_async():
        yield configured
    await runtime.dispose()


async def run_pending(worker: procrastinate.App) -> None:
    """Process every job waiting in the test queue, then return."""
    await worker.run_worker_async(
        queues=[QUEUE], wait=False, install_signal_handlers=False, listen_notify=False
    )


async def job_rows(owner_engine: AsyncEngine, task: str) -> list[tuple[str, int]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT status::text, attempts FROM procrastinate_jobs WHERE task_name = :t"),
            {"t": task},
        )
        return [(r.status, r.attempts) for r in rows]


async def two_tenants(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Org A and org B, each with one company. Returns (org_a, company_a, company_b)."""
    org_a, org_b, company_a, company_b = (uuid.uuid4() for _ in range(4))
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:a, 'A'), (:b, 'B')"),
            {"a": org_a, "b": org_b},
        )
        await conn.execute(
            text(
                "INSERT INTO companies (id, organization_id, name, source) VALUES "
                "(:ca, :a, 'Acme', 'manual'), (:cb, :b, 'Globex', 'manual')"
            ),
            {"ca": company_a, "cb": company_b, "a": org_a, "b": org_b},
        )
    return org_a, company_a, company_b


async def test_enqueue_is_part_of_the_callers_transaction(
    engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    sessions = create_sessionmaker(engine)
    async with sessions() as db:
        await enqueue(db, "tests.always_fails", queue=QUEUE)
        await db.rollback()  # e.g. the request failed after asking for the job
    assert await job_rows(owner_engine, "tests.always_fails") == []

    async with sessions() as db:
        job_id = await enqueue(db, "tests.always_fails", queue=QUEUE)
        await db.commit()
    assert job_id is not None
    assert await job_rows(owner_engine, "tests.always_fails") == [("todo", 0)]


async def test_queueing_lock_refuses_a_duplicate_without_breaking_the_transaction(
    engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    async with create_sessionmaker(engine)() as db:
        first = await enqueue(db, "tests.always_fails", queue=QUEUE, queueing_lock="same")
        second = await enqueue(db, "tests.always_fails", queue=QUEUE, queueing_lock="same")
        await db.execute(text("SELECT 1"))  # the transaction is still usable
        await db.commit()

    assert first is not None
    assert second is None
    assert len(await job_rows(owner_engine, "tests.always_fails")) == 1


async def test_job_works_on_its_own_tenant_across_commits(
    engine: AsyncEngine, owner_engine: AsyncEngine, worker: procrastinate.App
) -> None:
    org_a, company_a, _ = await two_tenants(owner_engine)
    async with create_sessionmaker(engine)() as db:
        await enqueue(
            db, "tests.rename_company", queue=QUEUE,
            organization_id=org_a, company_id=company_a, name="Acme Renamed",
        )  # fmt: skip
        await db.commit()

    await run_pending(worker)

    assert await job_rows(owner_engine, "tests.rename_company") == [("succeeded", 1)]
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT name, city FROM companies WHERE id = :id"), {"id": company_a}
            )
        ).one()
    assert tuple(row) == ("Acme Renamed", "Updated")


async def test_job_cannot_touch_another_tenants_data(
    engine: AsyncEngine, owner_engine: AsyncEngine, worker: procrastinate.App
) -> None:
    """A job for org A that names org B's company finds nothing: RLS applies in the worker."""
    org_a, _, company_b = await two_tenants(owner_engine)
    async with create_sessionmaker(engine)() as db:
        await enqueue(
            db, "tests.rename_company", queue=QUEUE,
            organization_id=org_a, company_id=company_b, name="Pwned",
        )  # fmt: skip
        await db.commit()

    await run_pending(worker)

    assert await job_rows(owner_engine, "tests.rename_company") == [("failed", 1)]
    async with owner_engine.connect() as conn:
        name = await conn.scalar(
            text("SELECT name FROM companies WHERE id = :id"), {"id": company_b}
        )
    assert name == "Globex"


async def test_failing_job_is_retried_then_marked_failed(
    engine: AsyncEngine, owner_engine: AsyncEngine, worker: procrastinate.App
) -> None:
    async with create_sessionmaker(engine)() as db:
        await enqueue(db, "tests.always_fails", queue=QUEUE)
        await db.commit()

    await run_pending(worker)

    assert await job_rows(owner_engine, "tests.always_fails") == [
        ("failed", 4)
    ]  # 1 run + 3 retries


def test_worker_connects_as_the_restricted_role(test_settings: Settings) -> None:
    info = conninfo(test_settings)

    assert f"user={APP_DB_ROLE}" in info
    assert f"user={test_settings.postgres_user} " not in f"{info} "  # never the owner role
