"""Request/response models for AI insights."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from sia.modules.enrichment.models import RunStatus
from sia.modules.insights.briefs import SourceKind
from sia.modules.protection.ai_access import UnavailableReason


class BriefRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    status: RunStatus
    failure_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CitationOut(BaseModel):
    source_id: str
    quote: str


class ClaimOut(BaseModel):
    text: str
    citations: list[CitationOut]


class OutreachOut(BaseModel):
    angle: str
    opening_line: str
    discovery_questions: list[str]
    citations: list[CitationOut]


class BriefSourceOut(BaseModel):
    id: str
    kind: SourceKind
    title: str
    url: str | None


class BriefOut(BaseModel):
    summary: list[ClaimOut]
    fit: list[ClaimOut]
    key_facts: list[ClaimOut]
    priorities: list[ClaimOut]  # the model's inferences, each citing its evidence
    outreach: OutreachOut | None
    gaps: list[str]
    sources: list[BriefSourceOut]
    claims_kept: int
    claims_dropped: int
    model: str
    generated_at: datetime
    stale: bool  # the company's data changed since the brief was written


class CompanyBriefOut(BaseModel):
    latest_run: BriefRunOut | None
    brief: BriefOut | None


class PurposeUsage(BaseModel):
    purpose: str
    calls: int
    cost_usd: str


class AIUsageOut(BaseModel):
    """AI spend of the organisation (estimates; the Anthropic bill is authoritative)."""

    cost_today_usd: str
    cost_month_usd: str
    month_by_purpose: list[PurposeUsage]
    briefs_today: int
    brief_daily_limit: int
    available: bool  # may this workspace use AI right now?
    unavailable_reason: UnavailableReason | None
