"""ICP management and rescoring (ADR-0011).

When scores are recalculated:
- one company changed (edit, contact added/removed, enrichment finished): synchronously, in the
  SAME transaction as the change, so a committed change always has a matching score;
- many companies changed (ICP saved, CSV import): a background job rescoring the organisation,
  enqueued in the same transaction as the change (so it cannot be lost). A queueing lock keeps
  at most one waiting job per organisation; the job always reads the latest ICP when it runs.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.errors import NotFoundError
from sia.core.jobs import enqueue
from sia.modules.companies import repository as companies_repository
from sia.modules.companies.models import Company
from sia.modules.contacts.models import Contact
from sia.modules.enrichment.models import CompanyProfile
from sia.modules.identity.service import TenantContext
from sia.modules.scoring.criteria import ICPDefinition
from sia.modules.scoring.engine import CompanyFacts, ScoreResult, score_company, tier_for
from sia.modules.scoring.models import CompanyScore, ICPProfile
from sia.modules.scoring.schemas import (
    CompanyScoreOut,
    CriterionOut,
    ICPOut,
    ICPPreview,
    PreviewCompany,
    ScoringStatus,
    TierCounts,
)

logger = structlog.get_logger(__name__)

TASK_NAME = "scoring.rescore_organization"
QUEUE = "scoring"
BATCH = 1000
PREVIEW_TOP = 10


# --- Facts: everything the engine may look at, loaded in bulk ---------------------------------


def _fact_value(facts: dict[str, Any], name: str) -> str | None:
    fact = facts.get(name)
    if isinstance(fact, dict) and fact.get("value") not in (None, ""):
        return str(fact["value"])
    return None


def _fact_values(facts: dict[str, Any], name: str) -> list[str]:
    items = facts.get(name)
    if not isinstance(items, list):
        return []
    return [str(i["value"]) for i in items if isinstance(i, dict) and i.get("value")]


def build_facts(
    company: Any, profile_facts: dict[str, Any] | None, contact_count: int
) -> CompanyFacts:
    """`profile_facts` are the VERIFIED facts of the company's AI profile (or None)."""
    facts = profile_facts or {}
    texts: list[tuple[str, str]] = []
    if company.description:
        texts.append(("description", company.description))
    if description := _fact_value(facts, "description"):
        texts.append(("website summary", description))
    texts += [("website products", v) for v in _fact_values(facts, "products")]
    texts += [("website target customers", v) for v in _fact_values(facts, "target_customers")]
    return CompanyFacts(
        industry=company.industry,
        ai_industry=_fact_value(facts, "industry"),
        employee_count=company.employee_count,
        ai_employee_range=_fact_value(facts, "employee_range"),
        country=company.country,
        ai_country=_fact_value(facts, "headquarters_country"),
        ai_business_model=_fact_value(facts, "business_model"),
        texts=texts,
        contact_count=contact_count,
    )


async def _load_facts(
    db: AsyncSession, organization_id: uuid.UUID, company_ids: list[uuid.UUID]
) -> list[tuple[Any, CompanyFacts]]:
    """(company row, facts) for each existing company, in one query per source."""
    if not company_ids:
        return []
    companies = (
        await db.execute(
            select(
                Company.id,
                Company.name,
                Company.industry,
                Company.employee_count,
                Company.country,
                Company.description,
            ).where(Company.organization_id == organization_id, Company.id.in_(company_ids))
        )
    ).all()
    profiles: dict[uuid.UUID, dict[str, Any]] = dict(
        (
            await db.execute(
                select(CompanyProfile.company_id, CompanyProfile.facts).where(
                    CompanyProfile.organization_id == organization_id,
                    CompanyProfile.company_id.in_(company_ids),
                )
            )
        ).all()
    )
    counts: dict[uuid.UUID | None, int] = dict(
        (
            await db.execute(
                select(Contact.company_id, func.count())
                .where(
                    Contact.organization_id == organization_id,
                    Contact.company_id.in_(company_ids),
                )
                .group_by(Contact.company_id)
            )
        ).all()
    )
    return [(c, build_facts(c, profiles.get(c.id), counts.get(c.id, 0))) for c in companies]


async def _id_batches(db: AsyncSession, organization_id: uuid.UUID) -> Any:
    """All company IDs of the organisation, BATCH at a time (keyset, so no OFFSET scans)."""
    after: uuid.UUID | None = None
    while True:
        query = select(Company.id).where(Company.organization_id == organization_id)
        if after is not None:
            query = query.where(Company.id > after)
        ids = list(await db.scalars(query.order_by(Company.id).limit(BATCH)))
        if not ids:
            return
        yield ids
        after = ids[-1]


# --- Scoring and storing --------------------------------------------------------------------


async def _current_icp(
    db: AsyncSession, organization_id: uuid.UUID
) -> tuple[ICPDefinition, int] | None:
    profile = await db.get(ICPProfile, organization_id)
    if profile is None:
        return None
    return ICPDefinition.model_validate(profile.definition), profile.version


async def _store(
    db: AsyncSession, organization_id: uuid.UUID, version: int, scored: dict[uuid.UUID, ScoreResult]
) -> None:
    if not scored:
        return
    insert = pg_insert(CompanyScore).values(
        [
            {
                "organization_id": organization_id,
                "company_id": company_id,
                "score": r.score,
                "disqualified": r.disqualified,
                "completeness": r.completeness,
                "breakdown": r.breakdown(),
                "icp_version": version,
            }
            for company_id, r in scored.items()
        ]
    )
    await db.execute(
        insert.on_conflict_do_update(
            index_elements=["organization_id", "company_id"],
            set_={
                "score": insert.excluded.score,
                "disqualified": insert.excluded.disqualified,
                "completeness": insert.excluded.completeness,
                "breakdown": insert.excluded.breakdown,
                "icp_version": insert.excluded.icp_version,
                "scored_at": func.now(),
            },
        )
    )
    await companies_repository.set_icp_scores(
        db, organization_id, {company_id: r.score for company_id, r in scored.items()}
    )


async def rescore_companies(
    db: AsyncSession, organization_id: uuid.UUID, company_ids: Iterable[uuid.UUID | None]
) -> int:
    """Rescore specific companies now, in the caller's transaction (no commit). Returns how many
    were scored (0 when the organisation has no ICP)."""
    ids = sorted({i for i in company_ids if i is not None})
    if not ids:
        return 0
    current = await _current_icp(db, organization_id)
    if current is None:
        return 0
    icp, version = current
    total = 0
    for start in range(0, len(ids), BATCH):
        rows = await _load_facts(db, organization_id, ids[start : start + BATCH])
        await _store(db, organization_id, version, {c.id: score_company(icp, f) for c, f in rows})
        total += len(rows)
    return total


async def request_full_rescore(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Queue a rescore of every company, in the caller's transaction (no commit). Does nothing
    when the organisation has no ICP."""
    if await db.get(ICPProfile, organization_id) is None:
        return
    await enqueue(
        db,
        TASK_NAME,
        queue=QUEUE,
        queueing_lock=f"rescore:{organization_id}",
        organization_id=organization_id,
    )


async def rescore_organization(db: AsyncSession, organization_id: uuid.UUID) -> int:
    """Rescore every company, committing per batch (short transactions, visible progress).
    Called by the worker with a tenant-scoped session."""
    total = 0
    async for ids in _id_batches(db, organization_id):
        scored = await rescore_companies(db, organization_id, ids)
        await db.commit()
        if scored == 0:
            break  # the ICP was deleted meanwhile
        total += scored
    logger.info("organization_rescored", organization_id=str(organization_id), companies=total)
    return total


# --- API-facing operations --------------------------------------------------------------------


async def _status(db: AsyncSession, organization_id: uuid.UUID, version: int) -> ScoringStatus:
    total = await db.scalar(
        select(func.count()).select_from(Company).where(Company.organization_id == organization_id)
    )
    current = await db.scalar(
        select(func.count())
        .select_from(CompanyScore)
        .where(CompanyScore.organization_id == organization_id, CompanyScore.icp_version == version)
    )
    return ScoringStatus(total_companies=total or 0, scored_current=current or 0)


async def get_icp(db: AsyncSession, tenant: TenantContext) -> ICPOut | None:
    profile = await db.get(ICPProfile, tenant.organization_id)
    if profile is None:
        return None
    return ICPOut(
        definition=ICPDefinition.model_validate(profile.definition),
        version=profile.version,
        updated_at=profile.updated_at,
        status=await _status(db, tenant.organization_id, profile.version),
    )


async def save_icp(db: AsyncSession, tenant: TenantContext, definition: ICPDefinition) -> ICPOut:
    profile = await db.get(ICPProfile, tenant.organization_id, with_for_update=True)
    if profile is None:
        profile = ICPProfile(organization_id=tenant.organization_id, version=0)
        db.add(profile)
    profile.definition = definition.model_dump(mode="json")
    profile.version += 1
    profile.updated_by_user_id = tenant.user.id
    profile.updated_at = datetime.now(UTC)
    await db.flush()
    await request_full_rescore(db, tenant.organization_id)
    out = ICPOut(
        definition=definition,
        version=profile.version,
        updated_at=profile.updated_at,
        status=await _status(db, tenant.organization_id, profile.version),
    )
    await db.commit()
    logger.info("icp_saved", version=out.version, criteria=len(definition.criteria))
    return out


async def delete_icp(db: AsyncSession, tenant: TenantContext) -> None:
    org = tenant.organization_id
    await db.execute(delete(ICPProfile).where(ICPProfile.organization_id == org))
    await db.execute(delete(CompanyScore).where(CompanyScore.organization_id == org))
    await companies_repository.clear_icp_scores(db, org)
    await db.commit()
    logger.info("icp_deleted")


async def request_rescore(db: AsyncSession, tenant: TenantContext) -> None:
    if await db.get(ICPProfile, tenant.organization_id) is None:
        raise NotFoundError("Define your ideal customer profile first.")
    await request_full_rescore(db, tenant.organization_id)
    await db.commit()


async def preview(db: AsyncSession, tenant: TenantContext, definition: ICPDefinition) -> ICPPreview:
    """Score every company against an unsaved ICP, in memory. Nothing is written."""
    tiers = TierCounts()
    top: list[PreviewCompany] = []
    completeness = 0.0
    total = 0
    async for ids in _id_batches(db, tenant.organization_id):
        for company, facts in await _load_facts(db, tenant.organization_id, ids):
            result = score_company(definition, facts)
            setattr(tiers, result.tier, getattr(tiers, result.tier) + 1)
            completeness += result.completeness
            total += 1
            top.append(
                PreviewCompany(
                    company_id=company.id, name=company.name, score=result.score, tier=result.tier
                )
            )
        top = sorted(top, key=lambda c: (-c.score, c.name.casefold()))[:PREVIEW_TOP]
    return ICPPreview(
        total_companies=total,
        tiers=tiers,
        top=top,
        average_completeness=round(completeness / total, 2) if total else 0.0,
    )


async def company_score(
    db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID
) -> CompanyScoreOut | None:
    """The stored score with its breakdown; None when there's no ICP or no score yet."""
    if await companies_repository.get(db, tenant.organization_id, company_id) is None:
        raise NotFoundError("Company not found.")
    profile = await db.get(ICPProfile, tenant.organization_id)
    score = await db.get(CompanyScore, (tenant.organization_id, company_id))
    if profile is None or score is None:
        return None
    return CompanyScoreOut(
        score=score.score,
        tier=tier_for(score.score),
        disqualified=score.disqualified,
        completeness=score.completeness,
        breakdown=[CriterionOut.model_validate(item) for item in score.breakdown],
        icp_version=score.icp_version,
        current=score.icp_version == profile.version,
        scored_at=score.scored_at,
    )
