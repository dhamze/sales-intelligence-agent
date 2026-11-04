"""HTTP routes for enrichment (thin: parse, call service, respond)."""

import uuid

from fastapi import APIRouter, status

from sia.core.db import DbSession
from sia.modules.enrichment import service
from sia.modules.enrichment.schemas import (
    CompanyEnrichmentOut,
    EnrichmentRunOut,
    EnrichmentUsageOut,
    EnrichRequest,
)
from sia.modules.identity.dependencies import AppSettings, CurrentTenant

router = APIRouter(tags=["enrichment"])


@router.post("/companies/{company_id}/enrich", status_code=status.HTTP_202_ACCEPTED)
async def enrich_company(
    company_id: uuid.UUID, tenant: CurrentTenant, db: DbSession, settings: AppSettings
) -> EnrichmentRunOut:
    """Queue (or return the already-active) enrichment run for one company."""
    runs = await service.request_enrichment(db, tenant, settings, [company_id])
    return runs[0]


@router.get("/companies/{company_id}/enrichment")
async def company_enrichment(
    company_id: uuid.UUID, tenant: CurrentTenant, db: DbSession
) -> CompanyEnrichmentOut:
    return await service.company_enrichment(db, tenant, company_id)


@router.post("/enrichment/runs", status_code=status.HTTP_202_ACCEPTED)
async def enrich_many(
    body: EnrichRequest, tenant: CurrentTenant, db: DbSession, settings: AppSettings
) -> list[EnrichmentRunOut]:
    return await service.request_enrichment(
        db, tenant, settings, body.company_ids, not_yet_enriched=body.not_yet_enriched
    )


@router.get("/enrichment/usage")
async def enrichment_usage(
    tenant: CurrentTenant, db: DbSession, settings: AppSettings
) -> EnrichmentUsageOut:
    return await service.usage(db, tenant, settings)
