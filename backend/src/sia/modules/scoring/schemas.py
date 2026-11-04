"""Request/response models for ICP scoring."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from sia.modules.scoring.criteria import ICPDefinition
from sia.modules.scoring.engine import Status, Tier


class ScoringStatus(BaseModel):
    total_companies: int
    scored_current: int  # scored with the current ICP version


class ICPOut(BaseModel):
    definition: ICPDefinition
    version: int
    updated_at: datetime
    status: ScoringStatus


class TierCounts(BaseModel):
    A: int = 0
    B: int = 0
    C: int = 0
    D: int = 0


class PreviewCompany(BaseModel):
    company_id: uuid.UUID
    name: str
    score: int
    tier: Tier


class ICPPreview(BaseModel):
    """What the ICP would do to the current companies, without saving anything."""

    total_companies: int
    tiers: TierCounts
    top: list[PreviewCompany]
    average_completeness: float


class CriterionOut(BaseModel):
    kind: str
    status: Status
    points: float
    max_points: int
    must_have: bool
    detail: str


class CompanyScoreOut(BaseModel):
    score: int
    tier: Tier
    disqualified: bool
    completeness: float
    breakdown: list[CriterionOut]
    icp_version: int
    current: bool  # False while a rescore after an ICP change is still pending
    scored_at: datetime
