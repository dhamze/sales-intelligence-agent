"""HTTP routes for AI insights (thin: parse, call service, respond)."""

import uuid

from fastapi import APIRouter, status

from sia.core.db import DbSession
from sia.modules.identity.dependencies import AppSettings, CurrentTenant
from sia.modules.insights import service
from sia.modules.insights.schemas import AIUsageOut, BriefRunOut, CompanyBriefOut

router = APIRouter(tags=["insights"])


@router.post("/companies/{company_id}/brief", status_code=status.HTTP_202_ACCEPTED)
async def request_brief(
    company_id: uuid.UUID, tenant: CurrentTenant, db: DbSession, settings: AppSettings
) -> BriefRunOut:
    """Queue (or return the already-active) brief run for one company."""
    return await service.request_brief(db, tenant, settings, company_id)


@router.get("/companies/{company_id}/brief")
async def company_brief(
    company_id: uuid.UUID, tenant: CurrentTenant, db: DbSession
) -> CompanyBriefOut:
    """The latest verified brief (with whether it's out of date) and the latest run."""
    return await service.company_brief(db, tenant, company_id)


@router.get("/ai/usage")
async def ai_usage(tenant: CurrentTenant, db: DbSession, settings: AppSettings) -> AIUsageOut:
    """Estimated AI spend today and this month, by purpose."""
    return await service.ai_usage(db, tenant, settings)
