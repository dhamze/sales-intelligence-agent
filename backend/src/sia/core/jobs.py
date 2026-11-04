"""Enqueueing background jobs (Procrastinate, ADR-0002).

`enqueue()` inserts the job through Procrastinate's versioned SQL function on OUR database
session, so the job is part of the caller's transaction: if the transaction rolls back, the job
never existed; if it commits, the job is guaranteed to be there. (Enqueueing through
Procrastinate's own connection pool would be a separate transaction, and a crash between the
two commits would leave a request recorded but never processed, or vice versa.)

The worker side lives in `sia.worker`.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.db import violates_constraint

DEFAULT_QUEUE = "default"
# Unique index in Procrastinate's schema: one waiting ("todo") job per queueing lock.
QUEUEING_LOCK_INDEX = "procrastinate_jobs_queueing_lock_idx_v1"


def _json_default(value: Any) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"Cannot serialise {type(value).__name__} into job arguments")


async def enqueue(
    db: AsyncSession,
    task_name: str,
    *,
    queue: str = DEFAULT_QUEUE,
    queueing_lock: str | None = None,
    **args: Any,
) -> int | None:
    """Add a job in the current transaction. Returns its id, or None when `queueing_lock` is set
    and an identical job is already waiting (Procrastinate refuses duplicates by lock)."""
    # Savepoint: a duplicate queueing lock must not abort the caller's whole transaction. The
    # error is caught OUTSIDE the savepoint block, so the savepoint is rolled back, not released.
    try:
        async with db.begin_nested():
            job_id = await db.scalar(
                text(
                    "SELECT unnest(procrastinate_defer_jobs_v1(ARRAY[ROW("
                    ":queue, :task, 0, NULL, :queueing_lock, CAST(:args AS jsonb), NULL"
                    ")::procrastinate_job_to_defer_v1]))"
                ),
                {
                    "queue": queue,
                    "task": task_name,
                    "queueing_lock": queueing_lock,
                    "args": json.dumps(args, default=_json_default),
                },
            )
    except IntegrityError as exc:
        if queueing_lock and violates_constraint(exc, QUEUEING_LOCK_INDEX):
            return None
        raise
    return int(job_id) if job_id is not None else None
