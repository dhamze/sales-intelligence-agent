"""Account brief workflow (ADR-0012).

API side (`request_brief`): checks the daily cap, creates a run AND enqueues its job in the same
transaction. Worker side (`run_brief`): gathers the sources, asks the model, verifies every
citation against the sources, stores the verified brief. Every AI call is logged with its cost.
"""

import uuid
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.ai.client import LLMClient, Outcome
from sia.ai.models import AIGeneration
from sia.ai.usage import log_generation
from sia.core.config import Effort, Settings
from sia.core.errors import NotFoundError, TooManyRequestsError
from sia.core.jobs import enqueue
from sia.modules.companies.models import Company
from sia.modules.contacts.models import Contact
from sia.modules.enrichment.models import RunStatus, WebPage
from sia.modules.identity.service import TenantContext
from sia.modules.insights.briefs import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    BriefOutput,
    Page,
    RecordFacts,
    ScoreFacts,
    Source,
    build_prompt,
    build_sources,
    fingerprint,
    verify,
)
from sia.modules.insights.models import AccountBrief, BriefRun
from sia.modules.insights.schemas import (
    AIUsageOut,
    BriefOut,
    BriefRunOut,
    CompanyBriefOut,
    PurposeUsage,
)
from sia.modules.protection.ai_access import blocked_in_worker, require_ai, unavailable_reason
from sia.modules.scoring.engine import tier_for
from sia.modules.scoring.models import CompanyScore, ICPProfile
from sia.worker.runtime import tenant_session

logger = structlog.get_logger(__name__)

TASK_NAME = "insights.generate_brief"
QUEUE = "insights"
PURPOSE = "account_brief"
ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)
MAX_OUTPUT_TOKENS = 8_000

_CRITERION_LABELS = {
    "industry": "Industry",
    "size": "Company size",
    "country": "Country",
    "business_model": "Business model",
    "keywords": "Keywords",
    "has_contacts": "Contacts on file",
}


def score_facts(score: int, breakdown: list[dict[str, Any]]) -> ScoreFacts:
    """The ICP fit as a brief source (S): the score plus one line per criterion."""
    return ScoreFacts(
        score=score,
        tier=tier_for(score),
        lines=[
            f"{_CRITERION_LABELS.get(item['kind'], item['kind'])}: "
            f"{item['status']} - {item['detail']}"
            for item in breakdown
        ],
    )


class BriefDailyLimitError(TooManyRequestsError):
    code = "brief_daily_limit"

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Today's limit of {limit} briefs has been reached. It resets at midnight (UTC).",
            details=[{"daily_limit": limit}],
        )


def _start_of_today() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


def _money(value: object) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.0001")))


# --- Sources: everything the brief may be written from ----------------------------------------


async def gather_sources(
    db: AsyncSession, organization_id: uuid.UUID, company_id: uuid.UUID
) -> tuple[str, list[Source]] | None:
    """(company name, sources), or None when the company doesn't exist (for this tenant)."""
    company = (
        await db.scalars(
            select(Company).where(
                Company.organization_id == organization_id, Company.id == company_id
            )
        )
    ).one_or_none()
    if company is None:
        return None
    pages = (
        await db.scalars(
            select(WebPage)
            .where(WebPage.organization_id == organization_id, WebPage.company_id == company_id)
            .order_by(WebPage.fetched_at, WebPage.url)
        )
    ).all()
    score = None
    if await db.get(ICPProfile, organization_id) is not None:
        stored = await db.get(CompanyScore, (organization_id, company_id))
        if stored is not None:
            score = score_facts(stored.score, stored.breakdown)
    contacts = (
        await db.execute(
            select(Contact.title).where(
                Contact.organization_id == organization_id, Contact.company_id == company_id
            )
        )
    ).all()
    titles = sorted({t for (t,) in contacts if t})
    sources = build_sources(
        RecordFacts(
            name=company.name,
            domain=company.domain,
            website=company.website,
            industry=company.industry,
            employee_count=company.employee_count,
            country=company.country,
            city=company.city,
            description=company.description,
        ),
        [Page(url=p.url, title=p.title, text=p.text) for p in pages],
        score,
        titles,
        len(contacts),
    )
    return company.name, sources


# --- API side -------------------------------------------------------------------------------


async def _briefs_today(db: AsyncSession, organization_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count()).where(
            BriefRun.organization_id == organization_id,
            BriefRun.created_at >= _start_of_today(),
        )
    )
    return count or 0


async def request_brief(
    db: AsyncSession, tenant: TenantContext, settings: Settings, company_id: uuid.UUID
) -> BriefRunOut:
    await require_ai(db, tenant.organization_id, settings)
    org = tenant.organization_id
    exists = await db.scalar(
        select(Company.id).where(Company.organization_id == org, Company.id == company_id)
    )
    if exists is None:
        raise NotFoundError("Company not found.")
    active = (
        await db.scalars(
            select(BriefRun).where(
                BriefRun.organization_id == org,
                BriefRun.company_id == company_id,
                BriefRun.status.in_(ACTIVE),
            )
        )
    ).first()
    if active is not None:
        return BriefRunOut.model_validate(active)
    if await _briefs_today(db, org) >= settings.brief_daily_limit:
        raise BriefDailyLimitError(settings.brief_daily_limit)

    run = BriefRun(
        id=uuid.uuid4(),
        organization_id=org,
        company_id=company_id,
        status=RunStatus.QUEUED,
        requested_by_user_id=tenant.user.id,
    )
    db.add(run)
    await db.flush()
    await enqueue(  # same transaction as the run row (see sia.core.jobs)
        db,
        TASK_NAME,
        queue=QUEUE,
        queueing_lock=f"brief:{company_id}",
        organization_id=org,
        company_id=company_id,
        run_id=run.id,
    )
    await db.refresh(run)
    out = BriefRunOut.model_validate(run)
    await db.commit()
    logger.info("brief_requested", company_id=str(company_id))
    return out


async def company_brief(
    db: AsyncSession, tenant: TenantContext, company_id: uuid.UUID
) -> CompanyBriefOut:
    org = tenant.organization_id
    gathered = await gather_sources(db, org, company_id)
    if gathered is None:
        raise NotFoundError("Company not found.")
    latest = (
        await db.scalars(
            select(BriefRun)
            .where(BriefRun.organization_id == org, BriefRun.company_id == company_id)
            .order_by(BriefRun.created_at.desc(), BriefRun.id.desc())
            .limit(1)
        )
    ).one_or_none()
    stored = await db.get(AccountBrief, (org, company_id))
    brief = None
    if stored is not None:
        brief = BriefOut.model_validate(
            {
                **stored.content,
                "sources": stored.sources,
                "claims_kept": stored.claims_kept,
                "claims_dropped": stored.claims_dropped,
                "model": stored.model,
                "generated_at": stored.generated_at,
                "stale": stored.input_fingerprint != fingerprint(gathered[1]),
            }
        )
    return CompanyBriefOut(
        latest_run=BriefRunOut.model_validate(latest) if latest else None, brief=brief
    )


async def ai_usage(db: AsyncSession, tenant: TenantContext, settings: Settings) -> AIUsageOut:
    org = tenant.organization_id
    today = _start_of_today()
    month = today.replace(day=1)
    rows = (
        await db.execute(
            select(
                AIGeneration.purpose,
                func.count(),
                func.coalesce(func.sum(AIGeneration.cost_usd), 0),
            )
            .where(AIGeneration.organization_id == org, AIGeneration.created_at >= month)
            .group_by(AIGeneration.purpose)
            .order_by(AIGeneration.purpose)
        )
    ).all()
    cost_today = await db.scalar(
        select(func.coalesce(func.sum(AIGeneration.cost_usd), 0)).where(
            AIGeneration.organization_id == org, AIGeneration.created_at >= today
        )
    )
    reason = await unavailable_reason(db, org, settings)
    return AIUsageOut(
        cost_today_usd=_money(cost_today),
        cost_month_usd=_money(sum((Decimal(str(cost)) for _, _, cost in rows), Decimal(0))),
        month_by_purpose=[
            PurposeUsage(purpose=purpose, calls=calls, cost_usd=_money(cost))
            for purpose, calls, cost in rows
        ],
        briefs_today=await _briefs_today(db, org),
        brief_daily_limit=settings.brief_daily_limit,
        available=reason is None,
        unavailable_reason=reason,
    )


# --- Worker side ----------------------------------------------------------------------------


async def _finish(
    db: AsyncSession, run: BriefRun, status: RunStatus, reason: str | None = None
) -> None:
    run.status = status
    run.failure_reason = reason
    run.finished_at = datetime.now(UTC)
    await db.commit()
    log = logger.info if status == RunStatus.SUCCEEDED else logger.warning
    log("brief_finished", run_id=str(run.id), status=status.value, reason=reason)


async def run_brief(
    *,
    organization_id: uuid.UUID,
    company_id: uuid.UUID,
    run_id: uuid.UUID,
    llm: LLMClient,
    effort: Effort = "medium",
    budget: Decimal | None = None,
) -> None:
    async with tenant_session(organization_id=organization_id) as db:
        run = await db.get(BriefRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return  # deleted with its company, or already handled
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        await db.commit()

        try:
            gathered = await gather_sources(db, organization_id, company_id)
            if gathered is None:
                await _finish(db, run, RunStatus.FAILED, "company_missing")
                return
            name, sources = gathered
            blocked = await blocked_in_worker(db, organization_id, budget)
            if blocked is not None:
                await _finish(db, run, RunStatus.FAILED, f"ai_{blocked}")
                return
            result = await llm.extract(
                system=SYSTEM_PROMPT,
                content=build_prompt(name, sources),
                output_type=BriefOutput,
                effort=effort,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            await log_generation(
                db,
                organization_id=organization_id,
                purpose=PURPOSE,
                subject_id=company_id,
                prompt_version=PROMPT_VERSION,
                result=result,
            )
            if result.outcome is not Outcome.SUCCESS or result.output is None:
                await _finish(db, run, RunStatus.FAILED, f"llm_{result.outcome.value}")
                return

            verified = verify(result.output, sources)
            brief = await db.get(AccountBrief, (organization_id, company_id))
            if brief is None:
                brief = AccountBrief(organization_id=organization_id, company_id=company_id)
                db.add(brief)
            brief.content = verified.content
            brief.sources = [s.public() for s in sources]
            brief.claims_kept = verified.kept
            brief.claims_dropped = verified.dropped
            brief.input_fingerprint = fingerprint(sources)
            brief.model = result.model
            brief.prompt_version = PROMPT_VERSION
            brief.generated_at = datetime.now(UTC)
            logger.info(
                "brief_stored",
                company_id=str(company_id),
                claims_kept=verified.kept,
                claims_dropped=verified.dropped,
                cost_usd=str(result.cost_usd),
            )
            await _finish(db, run, RunStatus.SUCCEEDED)
        except Exception:
            logger.exception("brief_crashed", run_id=str(run_id))
            await db.rollback()
            run = await db.get(BriefRun, run_id)
            if run is not None:
                await _finish(db, run, RunStatus.FAILED, "internal_error")
