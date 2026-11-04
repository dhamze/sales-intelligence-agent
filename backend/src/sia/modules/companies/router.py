"""HTTP routes for companies (thin: parse, call service, respond)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from sia.core.db import DbSession
from sia.core.pagination import Page
from sia.modules.companies import service
from sia.modules.companies.schemas import (
    CompanyCreate,
    CompanyFacets,
    CompanyListParams,
    CompanyOut,
    CompanyUpdate,
)
from sia.modules.identity.dependencies import AdminTenant, CurrentTenant

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("")
async def list_companies(
    params: Annotated[CompanyListParams, Query()], tenant: CurrentTenant, db: DbSession
) -> Page[CompanyOut]:
    return await service.list_companies(db, tenant, params)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_company(body: CompanyCreate, tenant: CurrentTenant, db: DbSession) -> CompanyOut:
    return await service.create_company(db, tenant, body)


# Declared before "/{company_id}" so "facets" is not parsed as a company ID.
@router.get("/facets")
async def get_facets(tenant: CurrentTenant, db: DbSession) -> CompanyFacets:
    return await service.get_facets(db, tenant)


@router.get("/{company_id}")
async def get_company(company_id: uuid.UUID, tenant: CurrentTenant, db: DbSession) -> CompanyOut:
    return await service.get_company(db, tenant, company_id)


@router.patch("/{company_id}")
async def update_company(
    company_id: uuid.UUID, body: CompanyUpdate, tenant: CurrentTenant, db: DbSession
) -> CompanyOut:
    return await service.update_company(db, tenant, company_id, body)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: uuid.UUID, tenant: AdminTenant, db: DbSession) -> None:
    await service.delete_company(db, tenant, company_id)
