"""May this organisation use AI right now? One place decides, for the API and the worker.

AI is unavailable when:
- the server has no AI provider configured (`not_configured`);
- the organisation isn't allowed to use AI (`disabled_for_org`; e.g. public demo signups);
- the installation's monthly AI budget is spent (`budget_exhausted`).

The API refuses new AI work, and the worker checks again right before calling the model (jobs
queued before the budget ran out must not overshoot it).
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.ai.models import AISpendDay
from sia.core.config import Settings
from sia.core.errors import AppError
from sia.modules.identity.models import Organization

UnavailableReason = Literal["not_configured", "disabled_for_org", "budget_exhausted"]

_MESSAGES: dict[str, str] = {
    "not_configured": "AI features are not configured on this server.",
    "disabled_for_org": "AI features are not enabled for this workspace.",
    "budget_exhausted": "AI features are paused: this month's AI budget has been used up.",
}


class AIUnavailableError(AppError):
    status_code = 503
    code = "ai_unavailable"

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(_MESSAGES[reason], details=[{"reason": reason}])
        self.reason = reason


def ai_configured(settings: Settings) -> bool:
    return settings.llm_provider == "fake" or settings.anthropic_api_key is not None


def _start_of_month() -> date:
    return datetime.now(UTC).date().replace(day=1)


async def month_spend(db: AsyncSession) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(AISpendDay.cost_usd), 0)).where(
            AISpendDay.day >= _start_of_month()
        )
    )
    return Decimal(str(total or 0))


async def unavailable_reason(
    db: AsyncSession, organization_id: uuid.UUID, settings: Settings
) -> UnavailableReason | None:
    if not ai_configured(settings):
        return "not_configured"
    enabled = await db.scalar(
        select(Organization.ai_enabled).where(Organization.id == organization_id)
    )
    if not enabled:
        return "disabled_for_org"
    budget = settings.ai_monthly_budget_usd
    if budget is not None and await month_spend(db) >= budget:
        return "budget_exhausted"
    return None


async def blocked_in_worker(
    db: AsyncSession, organization_id: uuid.UUID, budget: Decimal | None
) -> UnavailableReason | None:
    """The worker's last check before calling the model (the job may have waited a while)."""
    enabled = await db.scalar(
        select(Organization.ai_enabled).where(Organization.id == organization_id)
    )
    if not enabled:
        return "disabled_for_org"
    if budget is not None and await month_spend(db) >= budget:
        return "budget_exhausted"
    return None


async def require_ai(db: AsyncSession, organization_id: uuid.UUID, settings: Settings) -> None:
    reason = await unavailable_reason(db, organization_id, settings)
    if reason is not None:
        raise AIUnavailableError(reason)
