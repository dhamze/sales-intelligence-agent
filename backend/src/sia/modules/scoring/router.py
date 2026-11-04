"""HTTP routes for the ideal customer profile and scores (thin: parse, call service, respond)."""

import uuid

from fastapi import APIRouter, status

from sia.core.db import DbSession
from sia.modules.identity.dependencies import AdminTenant, CurrentTenant
from sia.modules.scoring import service
from sia.modules.scoring.criteria import ICPDefinition
from sia.modules.scoring.schemas import CompanyScoreOut, ICPOut, ICPPreview

router = APIRouter(tags=["scoring"])


@router.get("/icp")
async def get_icp(tenant: CurrentTenant, db: DbSession) -> ICPOut | None:
    """The organisation's ideal customer profile, or null when none is defined yet."""
    return await service.get_icp(db, tenant)


@router.put("/icp")
async def save_icp(body: ICPDefinition, tenant: AdminTenant, db: DbSession) -> ICPOut:
    """Create or replace the ICP (admins). All companies are rescored in the background."""
    return await service.save_icp(db, tenant, body)


@router.delete("/icp", status_code=status.HTTP_204_NO_CONTENT)
async def delete_icp(tenant: AdminTenant, db: DbSession) -> None:
    """Remove the ICP and every score (admins)."""
    await service.delete_icp(db, tenant)


@router.post("/icp/preview")
async def preview_icp(body: ICPDefinition, tenant: AdminTenant, db: DbSession) -> ICPPreview:
    """How an (unsaved) ICP would rate the current companies. Nothing is stored."""
    return await service.preview(db, tenant, body)


@router.post("/icp/rescore", status_code=status.HTTP_202_ACCEPTED)
async def rescore(tenant: AdminTenant, db: DbSession) -> None:
    """Recalculate every company's score in the background (admins)."""
    await service.request_rescore(db, tenant)


@router.get("/companies/{company_id}/score")
async def company_score(
    company_id: uuid.UUID, tenant: CurrentTenant, db: DbSession
) -> CompanyScoreOut | None:
    """The company's ICP fit with a per-criterion explanation; null without an ICP."""
    return await service.company_score(db, tenant, company_id)
