"""Request/response models for enrichment."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sia.modules.enrichment.models import RunStatus
from sia.modules.protection.ai_access import UnavailableReason


class EnrichmentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    status: RunStatus
    failure_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CompanyProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    facts: dict[str, Any] = Field(description="Verified facts: {field: {value, evidence[]}}")
    sources: list[dict[str, Any]]
    facts_kept: int
    facts_dropped: int = Field(description="Facts discarded because their quotes didn't verify")
    model: str
    generated_at: datetime


class CompanyEnrichmentOut(BaseModel):
    latest_run: EnrichmentRunOut | None
    profile: CompanyProfileOut | None


class EnrichRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    not_yet_enriched: bool = Field(
        default=False,
        description="Also queue companies that have never been enriched, up to today's quota",
    )


class EnrichmentUsageOut(BaseModel):
    used_today: int
    daily_limit: int
    remaining_today: int
    cost_today_usd: str
    available: bool  # may this workspace use AI right now?
    unavailable_reason: UnavailableReason | None
