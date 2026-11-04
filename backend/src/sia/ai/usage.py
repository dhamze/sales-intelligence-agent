"""Recording AI calls (every one, including failures) so spend is always accounted for."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sia.ai.client import StructuredResult
from sia.ai.models import AIGeneration


def log_generation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    purpose: str,
    subject_id: uuid.UUID | None,
    prompt_version: str,
    result: StructuredResult[Any],
) -> None:
    """Add the call to `ai_generations` (in the caller's transaction)."""
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
