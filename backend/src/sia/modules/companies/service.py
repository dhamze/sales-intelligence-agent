"""Company business logic. Each write function is one unit of work and commits on success."""

import uuid
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.db import violates_constraint
from sia.core.errors import ConflictError, NotFoundError
from sia.core.pagination import Page, build_page, decode_cursor
from sia.modules.companies import repository
from sia.modules.companies.models import Company, RecordSource
from sia.modules.companies.schemas import (
    CompanyCreate,
    CompanyListParams,
    CompanyOut,
    CompanyUpdate,
)
from sia.modules.identity.service import TenantContext

logger = structlog.get_logger(__name__)

DOMAIN_UNIQUE = "uq_companies_organization_id_domain"


class DomainTakenError(ConflictError):
    code = "domain_taken"

    def __init__(self, existing_id: uuid.UUID | None) -> None:
        super().__init__(
            "A company with this domain already exists.",
            details=[{"existing_company_id": str(existing_id)}] if existing_id else None,
        )


def _not_found() -> NotFoundError:
    return NotFoundError("Company not found.")


async def list_companies(
    db: AsyncSession, tenant: TenantContext, params: CompanyListParams
) -> Page[CompanyOut]:
    spec = repository.sort_spec(params)
    after = decode_cursor(params.cursor, spec) if params.cursor else None
    rows = await repository.list_companies(db, tenant.organization_id, params, spec, after)
    return build_page(
        rows, params.limit, spec, to_item=CompanyOut.model_validate, get_id=lambda c: c.id
    )


async def get_company(db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID) -> CompanyOut:
    company = await repository.get(db, tenant.organization_id, company_id)
    if company is None:
        raise _not_found()
    return CompanyOut.model_validate(company)


async def company_exists(db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID) -> bool:
    return await repository.get(db, tenant.organization_id, company_id) is not None


async def company_ids_by_domain(
    db: AsyncSession, tenant: TenantContext, domains: set[str]
) -> dict[str, uuid.UUID]:
    return await repository.ids_by_domain(db, tenant.organization_id, domains)


async def _ensure_domain_free(
    db: AsyncSession, tenant: TenantContext, domain: str | None, *, except_id: uuid.UUID | None
) -> None:
    if domain is None:
        return
    existing = await repository.get_by_domain(db, tenant.organization_id, domain)
    if existing is not None and existing.id != except_id:
        raise DomainTakenError(existing.id)


async def _flush_or_domain_taken(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race with a concurrent insert of the same domain
        if violates_constraint(exc, DOMAIN_UNIQUE):
            raise DomainTakenError(None) from exc
        raise


async def create_company(
    db: AsyncSession, tenant: TenantContext, data: CompanyCreate
) -> CompanyOut:
    await _ensure_domain_free(db, tenant, data.domain, except_id=None)
    company = Company(
        id=uuid.uuid4(),
        organization_id=tenant.organization_id,
        source=RecordSource.MANUAL,
        created_by_user_id=tenant.user.id,
        **data.model_dump(exclude_none=True),
    )
    db.add(company)
    await _flush_or_domain_taken(db)
    await db.refresh(company)  # load server-generated timestamps
    out = CompanyOut.model_validate(company)
    await db.commit()
    logger.info("company_created", company_id=str(company.id))
    return out


async def update_company(
    db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID, data: CompanyUpdate
) -> CompanyOut:
    company = await repository.get(db, tenant.organization_id, company_id)
    if company is None:
        raise _not_found()
    changes: dict[str, Any] = data.model_dump(exclude_unset=True)
    if "domain" in changes:
        await _ensure_domain_free(db, tenant, changes["domain"], except_id=company.id)
    for field, value in changes.items():
        setattr(company, field, value)
    await _flush_or_domain_taken(db)
    await db.refresh(company)
    out = CompanyOut.model_validate(company)
    await db.commit()
    logger.info("company_updated", company_id=str(company.id), fields=sorted(changes))
    return out


async def delete_company(db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID) -> None:
    company = await repository.get(db, tenant.organization_id, company_id)
    if company is None:
        raise _not_found()
    await db.delete(company)  # contacts keep existing; their company link is cleared
    await db.commit()
    logger.info("company_deleted", company_id=str(company_id))
