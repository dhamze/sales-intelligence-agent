"""Worker tasks for enrichment."""

import uuid

from sia.core.config import get_settings
from sia.modules.enrichment import service
from sia.modules.enrichment.providers import make_llm, make_site_reader
from sia.worker import app


@app.task(name=service.TASK_NAME, queue=service.QUEUE)
async def enrich_company(organization_id: str, company_id: str, run_id: str) -> None:
    settings = get_settings()
    llm = make_llm(settings)
    try:
        await service.run_enrichment(
            organization_id=uuid.UUID(organization_id),
            company_id=uuid.UUID(company_id),
            run_id=uuid.UUID(run_id),
            reader=make_site_reader(settings),
            llm=llm,
            effort=settings.enrichment_effort,
            budget=settings.ai_monthly_budget_usd,
        )
    finally:
        close = getattr(llm, "close", None)
        if close is not None:
            await close()
