"""Recording AI calls (every one, including failures) so spend is always accounted for."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sia.ai.client import StructuredResult
from sia.ai.models import AIGeneration, AISpendDay


async def log_generation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    purpose: str,
    subject_id: uuid.UUID | None,
    prompt_version: str,
    result: StructuredResult[Any],
) -> None:
    """Record the call in `ai_generations` and add its cost to today's installation-wide total
    (both in the caller's transaction)."""
    db.add(
        AIGeneration(
            organization_id=organization_id,
            purpose=purpose,
            subject_id=subject_id,
            model=result.model,
            prompt_version=prompt_version,
            outcome=result.outcome,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            request_id=result.request_id,
            stop_reason=result.stop_reason,
            error=(result.error or "")[:500] or None,
        )
    )
    insert = pg_insert(AISpendDay).values(
        day=datetime.now(UTC).date(), calls=1, cost_usd=result.cost_usd
    )
    await db.execute(
        insert.on_conflict_do_update(
            index_elements=["day"],
            set_={
                "calls": AISpendDay.calls + 1,
                "cost_usd": AISpendDay.cost_usd + insert.excluded.cost_usd,
            },
        )
    )
