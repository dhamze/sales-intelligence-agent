"""Load the sample dataset into an empty workspace (one transaction, no AI calls)."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.errors import ConflictError
from sia.modules.companies.models import Company, RecordSource
from sia.modules.contacts.models import Contact
from sia.modules.demo.ai_build import apply_fill, base_record
from sia.modules.demo.dataset import SAMPLE_COMPANIES, SAMPLE_ICP
from sia.modules.enrichment.models import CompanyProfile, WebPage
from sia.modules.enrichment.service import fill_values
from sia.modules.identity.service import TenantContext
from sia.modules.insights.briefs import BriefOutput, fingerprint, verify
from sia.modules.insights.models import AccountBrief
from sia.modules.insights.service import gather_sources
from sia.modules.scoring import service as scoring
from sia.modules.scoring.criteria import ICPDefinition
from sia.modules.scoring.models import ICPProfile

logger = structlog.get_logger(__name__)

SAMPLE_AI_PATH = Path(__file__).with_name("sample_ai.json")
SAMPLE_MARKER = {"Sample data": "Fictional company"}


class WorkspaceNotEmptyError(ConflictError):
    code = "workspace_not_empty"

    def __init__(self) -> None:
        super().__init__("Sample data can only be loaded into an empty workspace.")


class SampleDataOut(BaseModel):
    companies: int
    contacts: int
    ai_profiles: int
    briefs: int


def load_ai() -> dict[str, Any] | None:
    """The pre-generated AI content, if it has been built (see sia.scripts.build_sample_ai)."""
    if not SAMPLE_AI_PATH.exists():
        return None
    data: dict[str, Any] = json.loads(SAMPLE_AI_PATH.read_text(encoding="utf-8"))
    return data


async def load_sample_data(db: AsyncSession, tenant: TenantContext) -> SampleDataOut:
    org = tenant.organization_id
    existing = await db.scalar(
        select(func.count()).select_from(Company).where(Company.organization_id == org)
    )
    if existing:
        raise WorkspaceNotEmptyError()

    ai = load_ai() or {}
    entries: dict[str, Any] = ai.get("companies", {})
    now = datetime.now(UTC)
    ids: dict[str, uuid.UUID] = {}
    contacts = profiles = 0

    for sample in SAMPLE_COMPANIES:
        profile = (entries.get(sample.domain) or {}).get("profile")
        record = base_record(sample)
        if profile:
            record = apply_fill(record, fill_values(profile["facts"]))
        company_id = uuid.uuid4()
        ids[sample.domain] = company_id
        db.add(
            Company(
                id=company_id,
                organization_id=org,
                source=RecordSource.IMPORT,
                created_by_user_id=tenant.user.id,
                attributes=dict(SAMPLE_MARKER),
                **record,
            )
        )
    await db.flush()  # companies before the rows that reference them

    for sample in SAMPLE_COMPANIES:
        company_id = ids[sample.domain]
        for person in sample.contacts:
            db.add(
                Contact(
                    id=uuid.uuid4(),
                    organization_id=org,
                    company_id=company_id,
                    first_name=person.first_name,
                    last_name=person.last_name,
                    title=person.title,
                    source=RecordSource.IMPORT,
                    created_by_user_id=tenant.user.id,
                )
            )
            contacts += 1
        for page in sample.pages:
            db.add(
                WebPage(
                    organization_id=org,
                    company_id=company_id,
                    url=sample.page_url(page),
                    title=page.title,
                    text=page.text,
                    fetched_at=now,
                )
            )
        profile = (entries.get(sample.domain) or {}).get("profile")
        if profile:
            db.add(
                CompanyProfile(
                    organization_id=org,
                    company_id=company_id,
                    facts=profile["facts"],
                    sources=[
                        {"url": sample.page_url(p), "title": p.title, "fetched_at": now.isoformat()}
                        for p in sample.pages
                    ],
                    facts_kept=profile["kept"],
                    facts_dropped=profile["dropped"],
                    model=profile["model"],
                    prompt_version=ai.get("profile_prompt_version", "unknown"),
                    generated_at=now,
                )
            )
            profiles += 1

    if await db.get(ICPProfile, org) is None:  # never replace a profile the team defined
        db.add(
            ICPProfile(
                organization_id=org,
                definition=ICPDefinition.model_validate(SAMPLE_ICP).model_dump(mode="json"),
                version=1,
                updated_by_user_id=tenant.user.id,
            )
        )
    await db.flush()
    await scoring.rescore_companies(db, org, ids.values())

    written = 0
    for sample in SAMPLE_COMPANIES:
        brief = (entries.get(sample.domain) or {}).get("brief")
        if not brief:
            continue
        gathered = await gather_sources(db, org, ids[sample.domain])
        if gathered is None:
            continue
        _, sources = gathered
        # Re-check every citation against the sources AS LOADED (same check as production):
        # if the dataset changed after the content was generated, a citation could otherwise
        # point at the wrong text. Anything that no longer holds is dropped, never shown.
        rechecked = verify(BriefOutput.model_validate(brief["content"]), sources)
        if rechecked.dropped:
            logger.warning(
                "sample_brief_citations_dropped",
                company=sample.domain,
                dropped=rechecked.dropped,
            )
        db.add(
            AccountBrief(
                organization_id=org,
                company_id=ids[sample.domain],
                content=rechecked.content,
                sources=[s.public() for s in sources],
                claims_kept=rechecked.kept,
                claims_dropped=brief["dropped"] + rechecked.dropped,
                input_fingerprint=fingerprint(sources),
                model=brief["model"],
                prompt_version=ai.get("brief_prompt_version", "unknown"),
                generated_at=now,
            )
        )
        written += 1

    out = SampleDataOut(companies=len(ids), contacts=contacts, ai_profiles=profiles, briefs=written)
    await db.commit()
    logger.info("sample_data_loaded", **out.model_dump())
    return out
