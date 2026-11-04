"""Enrichment workflow.

API side (`request_enrichment`): checks the daily quota, then creates a run per company AND
enqueues its job in the same transaction.

Worker side (`run_enrichment`): reads the website, asks the model for a profile with evidence,
verifies every quote against the fetched text, stores the verified profile and the pages, and
fills only EMPTY company fields. Every AI call is logged with its cost, including failures.
"""

import uuid
from datetime import UTC, datetime, time
from decimal import Decimal

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.ai.client import LLMClient, Outcome, StructuredResult
from sia.ai.models import AIGeneration
from sia.ai.usage import log_generation
from sia.core.config import Effort, Settings
from sia.core.errors import NotFoundError, TooManyRequestsError
from sia.core.jobs import enqueue
from sia.modules.companies import service as companies
from sia.modules.companies.models import Company
from sia.modules.enrichment.extraction import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ExtractedProfile,
    build_prompt,
    verify,
)
from sia.modules.enrichment.fetcher import FetchError, PageText
from sia.modules.enrichment.models import CompanyProfile, EnrichmentRun, RunStatus, WebPage
from sia.modules.enrichment.providers import (
    EnrichmentUnavailableError,
    SiteReader,
    llm_configured,
)
from sia.modules.enrichment.schemas import (
    CompanyEnrichmentOut,
    CompanyProfileOut,
    EnrichmentRunOut,
    EnrichmentUsageOut,
)
from sia.modules.identity.service import TenantContext
from sia.modules.scoring import service as scoring
from sia.worker.runtime import tenant_session

logger = structlog.get_logger(__name__)

TASK_NAME = "enrichment.enrich_company"
QUEUE = "enrichment"
PURPOSE = "company_profile"
ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)


class DailyLimitError(TooManyRequestsError):
    code = "enrichment_daily_limit"

    def __init__(self, remaining: int, limit: int) -> None:
        super().__init__(
            f"Daily enrichment limit reached ({remaining} of {limit} left today).",
            details=[{"remaining_today": remaining, "daily_limit": limit}],
        )


def _start_of_today() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


# --- API side ------------------------------------------------------------------------------------


async def usage(db: AsyncSession, tenant: TenantContext, settings: Settings) -> EnrichmentUsageOut:
    since = _start_of_today()
    used = await db.scalar(
        select(func.count()).where(
            EnrichmentRun.organization_id == tenant.organization_id,
            EnrichmentRun.created_at >= since,
        )
    )
    cost = await db.scalar(
        select(func.coalesce(func.sum(AIGeneration.cost_usd), 0)).where(
            AIGeneration.organization_id == tenant.organization_id,
            AIGeneration.created_at >= since,
        )
    )
    used = used or 0
    return EnrichmentUsageOut(
        used_today=used,
        daily_limit=settings.enrichment_daily_limit,
        remaining_today=max(settings.enrichment_daily_limit - used, 0),
        cost_today_usd=str(Decimal(cost or 0).quantize(Decimal("0.0001"))),
        configured=llm_configured(settings),
    )


async def _never_enriched(
    db: AsyncSession, organization_id: uuid.UUID, limit: int
) -> list[uuid.UUID]:
    # A read-only join with companies: selecting candidates in SQL beats loading every ID.
    profiled = select(CompanyProfile.company_id).where(
        CompanyProfile.organization_id == organization_id
    )
    attempted = select(EnrichmentRun.company_id).where(
        EnrichmentRun.organization_id == organization_id
    )
    rows = await db.scalars(
        select(Company.id)
        .where(
            Company.organization_id == organization_id,
            Company.id.not_in(profiled),
            Company.id.not_in(attempted),
            (Company.domain.is_not(None)) | (Company.website.is_not(None)),
        )
        .order_by(Company.created_at, Company.id)
        .limit(limit)
    )
    return list(rows)


async def request_enrichment(
    db: AsyncSession,
    tenant: TenantContext,
    settings: Settings,
    company_ids: list[uuid.UUID],
    *,
    not_yet_enriched: bool = False,
) -> list[EnrichmentRunOut]:
    if not llm_configured(settings):
        raise EnrichmentUnavailableError()

    wanted = list(dict.fromkeys(company_ids))  # de-duplicate, keep order
    known = await companies.company_names(db, tenant, set(wanted))
    if len(known) != len(wanted):
        raise NotFoundError("Company not found.")

    current = await usage(db, tenant, settings)
    if not_yet_enriched:
        extra = await _never_enriched(db, tenant.organization_id, current.remaining_today)
        wanted += [c for c in extra if c not in known]

    active = {
        run.company_id: run
        for run in await db.scalars(
            select(EnrichmentRun).where(
                EnrichmentRun.organization_id == tenant.organization_id,
                EnrichmentRun.company_id.in_(wanted),
                EnrichmentRun.status.in_(ACTIVE),
            )
        )
    }
    new = [c for c in wanted if c not in active]
    if len(new) > current.remaining_today:
        raise DailyLimitError(current.remaining_today, settings.enrichment_daily_limit)

    runs: list[EnrichmentRun] = []
    for company_id in new:
        run = EnrichmentRun(
            id=uuid.uuid4(),
            organization_id=tenant.organization_id,
            company_id=company_id,
            status=RunStatus.QUEUED,
            requested_by_user_id=tenant.user.id,
        )
        db.add(run)
        runs.append(run)
    await db.flush()
    for run in runs:  # same transaction as the run rows (see sia.core.jobs)
        await enqueue(
            db,
            TASK_NAME,
            queue=QUEUE,
            queueing_lock=f"enrich:{run.company_id}",
            organization_id=tenant.organization_id,
            company_id=run.company_id,
            run_id=run.id,
        )
    for run in runs:
        await db.refresh(run)
    out = [EnrichmentRunOut.model_validate(r) for r in [*runs, *active.values()]]
    await db.commit()
    logger.info("enrichment_requested", queued=len(runs), already_active=len(active))
    return out


async def company_enrichment(
    db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID
) -> CompanyEnrichmentOut:
    if not await companies.company_exists(db, tenant, company_id):
        raise NotFoundError("Company not found.")
    latest = (
        await db.scalars(
            select(EnrichmentRun)
            .where(
                EnrichmentRun.organization_id == tenant.organization_id,
                EnrichmentRun.company_id == company_id,
            )
            .order_by(EnrichmentRun.created_at.desc(), EnrichmentRun.id.desc())
            .limit(1)
        )
    ).one_or_none()
    profile = await db.get(CompanyProfile, (tenant.organization_id, company_id))
    return CompanyEnrichmentOut(
        latest_run=EnrichmentRunOut.model_validate(latest) if latest else None,
        profile=CompanyProfileOut.model_validate(profile) if profile else None,
    )


# --- Worker side ---------------------------------------------------------------------------------


def _log_generation(
    db: AsyncSession,
    organization_id: uuid.UUID,
    company_id: uuid.UUID,
    result: StructuredResult[ExtractedProfile],
) -> None:
    log_generation(
        db,
        organization_id=organization_id,
        purpose=PURPOSE,
        subject_id=company_id,
        prompt_version=PROMPT_VERSION,
        result=result,
    )


async def _finish(
    db: AsyncSession, run: EnrichmentRun, status: RunStatus, reason: str | None
) -> None:
    run.status = status
    run.failure_reason = reason
    run.finished_at = datetime.now(UTC)
    await db.commit()
    log = logger.info if status == RunStatus.SUCCEEDED else logger.warning
    log("enrichment_finished", run_id=str(run.id), status=status.value, reason=reason)


async def run_enrichment(
    *,
    organization_id: uuid.UUID,
    company_id: uuid.UUID,
    run_id: uuid.UUID,
    reader: SiteReader,
    llm: LLMClient,
    effort: Effort = "low",
) -> None:
    async with tenant_session(organization_id=organization_id) as db:
        run = await db.get(EnrichmentRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return  # cancelled, deleted with its company, or already handled
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        await db.commit()

        try:
            company = await companies.get_for_organization(db, organization_id, company_id)
            website = company and (
                company.website or (f"https://{company.domain}" if company.domain else None)
            )
            if company is None or not website:
                await _finish(db, run, RunStatus.FAILED, "no_website")
                return
            name = company.name

            try:
                pages = await reader.read(website)
            except FetchError as exc:
                await _finish(db, run, RunStatus.FAILED, f"fetch_{exc.reason.value}")
                return

            result = await llm.extract(
                system=SYSTEM_PROMPT,
                content=build_prompt(name, pages),
                output_type=ExtractedProfile,
                effort=effort,
            )
            _log_generation(db, organization_id, company_id, result)
            if result.outcome is not Outcome.SUCCESS or result.output is None:
                await _finish(db, run, RunStatus.FAILED, f"llm_{result.outcome.value}")
                return

            await _store(db, organization_id, company_id, pages, result.output, result.model)
            await _finish(db, run, RunStatus.SUCCEEDED, None)
        except Exception:
            logger.exception("enrichment_crashed", run_id=str(run_id))
            await db.rollback()
            run = await db.get(EnrichmentRun, run_id)
            if run is not None:
                await _finish(db, run, RunStatus.FAILED, "internal_error")


async def _store(
    db: AsyncSession,
    organization_id: uuid.UUID,
    company_id: uuid.UUID,
    pages: list[PageText],
    extracted: ExtractedProfile,
    model: str,
) -> None:
    verified = verify(extracted, pages)

    await db.execute(
        delete(WebPage).where(
            WebPage.organization_id == organization_id, WebPage.company_id == company_id
        )
    )
    db.add_all(
        WebPage(
            organization_id=organization_id,
            company_id=company_id,
            url=p.url,
            title=(p.title or "")[:500] or None,
            text=p.text,
            fetched_at=p.fetched_at,
        )
        for p in pages
    )
    profile = await db.get(CompanyProfile, (organization_id, company_id))
    if profile is None:
        profile = CompanyProfile(organization_id=organization_id, company_id=company_id)
        db.add(profile)
    profile.facts = verified.facts
    profile.sources = [
        {"url": p.url, "title": p.title, "fetched_at": p.fetched_at.isoformat()} for p in pages
    ]
    profile.facts_kept = verified.kept
    profile.facts_dropped = verified.dropped
    profile.model = model
    profile.prompt_version = PROMPT_VERSION
    profile.generated_at = datetime.now(UTC)

    facts = verified.facts

    def value(name: str) -> str | None:
        fact = facts.get(name)
        return str(fact["value"]) if isinstance(fact, dict) and fact.get("value") else None

    filled = await companies.fill_empty_fields(
        db,
        organization_id,
        company_id,
        {
            k: v
            for k, v in {
                "description": value("description"),
                "industry": value("industry"),
                "city": value("headquarters_city"),
                "country": value("headquarters_country"),
            }.items()
            if v
        },
    )
    await scoring.rescore_companies(db, organization_id, [company_id])
    logger.info(
        "enrichment_stored",
        company_id=str(company_id),
        facts_kept=verified.kept,
        facts_dropped=verified.dropped,
        filled=filled,
    )
