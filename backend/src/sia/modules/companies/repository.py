"""Data access for companies. Queries filter by organisation explicitly AND are filtered by
Row-Level Security in the database (two independent layers)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Float, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.pagination import SortSpec, keyset_condition, order_by
from sia.core.search import escape_like, use_search_threshold
from sia.modules.companies.models import Company
from sia.modules.companies.schemas import CompanyListParams


def relevance(q: str) -> ColumnElement[float]:
    """0..1 score: how well `q` matches a word sequence in the name or domain (pg_trgm)."""
    return cast(
        func.greatest(
            func.word_similarity(q, Company.name),
            func.word_similarity(q, func.coalesce(Company.domain, "")),
        ),
        Float,
    )


_SORTS: dict[str, tuple[Any, bool, type]] = {
    "name": (Company.name, False, str),
    "-name": (Company.name, True, str),
    "created_at": (Company.created_at, False, datetime),
    "-created_at": (Company.created_at, True, datetime),
    "updated_at": (Company.updated_at, False, datetime),
    "-updated_at": (Company.updated_at, True, datetime),
}


def sort_spec(params: CompanyListParams) -> SortSpec:
    key = params.sort or ("relevance" if params.q else "-created_at")
    if key == "relevance" and params.q:
        return SortSpec(key=key, column=relevance(params.q), descending=True, value_type=float)
    if key == "relevance":  # relevance needs a search term
        key = "-created_at"
    column, descending, value_type = _SORTS[key]
    return SortSpec(key=key, column=column, descending=descending, value_type=value_type)


def _conditions(organization_id: uuid.UUID, params: CompanyListParams) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [Company.organization_id == organization_id]
    if params.q:
        pattern = f"%{escape_like(params.q)}%"
        conditions.append(
            or_(
                literal(params.q).op("<%")(Company.name),  # word_similarity >= threshold
                literal(params.q).op("<%")(Company.domain),
                Company.name.ilike(pattern, escape="\\"),
                Company.domain.ilike(pattern, escape="\\"),
            )
        )
    if params.industry:
        conditions.append(func.lower(Company.industry).in_([v.lower() for v in params.industry]))
    if params.country:
        conditions.append(func.lower(Company.country).in_([v.lower() for v in params.country]))
    if params.employees_min is not None:
        conditions.append(Company.employee_count >= params.employees_min)
    if params.employees_max is not None:
        conditions.append(Company.employee_count <= params.employees_max)
    if params.source is not None:
        conditions.append(Company.source == params.source)
    if params.created_after is not None:
        conditions.append(Company.created_at >= params.created_after)
    if params.created_before is not None:
        conditions.append(Company.created_at < params.created_before)
    return conditions


async def list_companies(
    db: AsyncSession,
    organization_id: uuid.UUID,
    params: CompanyListParams,
    spec: SortSpec,
    after: tuple[Any, uuid.UUID] | None,
) -> list[tuple[Company, Any]]:
    """Returns up to limit+1 (company, sort value) rows; the extra row signals another page."""
    if params.q:
        await use_search_threshold(db)
    query = select(Company, spec.column.label("sort_value")).where(
        *_conditions(organization_id, params)
    )
    if after is not None:
        query = query.where(keyset_condition(spec, Company.id, after))
    query = query.order_by(*order_by(spec, Company.id)).limit(params.limit + 1)
    return [(company, value) for company, value in await db.execute(query)]


async def get(
    db: AsyncSession, organization_id: uuid.UUID, company_id: uuid.UUID
) -> Company | None:
    result = await db.scalars(
        select(Company).where(Company.organization_id == organization_id, Company.id == company_id)
    )
    return result.one_or_none()


async def get_by_domain(
    db: AsyncSession, organization_id: uuid.UUID, domain: str
) -> Company | None:
    result = await db.scalars(
        select(Company).where(Company.organization_id == organization_id, Company.domain == domain)
    )
    return result.one_or_none()


async def ids_by_domain(
    db: AsyncSession, organization_id: uuid.UUID, domains: set[str]
) -> dict[str, uuid.UUID]:
    if not domains:
        return {}
    rows = await db.execute(
        select(Company.domain, Company.id).where(
            Company.organization_id == organization_id, Company.domain.in_(domains)
        )
    )
    return {domain: company_id for domain, company_id in rows if domain}
