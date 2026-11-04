"""Worker tasks for AI insights."""

import uuid

from sia.core.config import get_settings
from sia.modules.insights import service
from sia.modules.insights.providers import make_brief_llm
from sia.worker import app


@app.task(name=service.TASK_NAME, queue=service.QUEUE)
async def generate_brief(organization_id: str, company_id: str, run_id: str) -> None:
    settings = get_settings()
    llm = make_brief_llm(settings)
    try:
        await service.run_brief(
            organization_id=uuid.UUID(organization_id),
            company_id=uuid.UUID(company_id),
            run_id=uuid.UUID(run_id),
            llm=llm,
            effort=settings.brief_effort,
        )
    finally:
        close = getattr(llm, "close", None)
        if close is not None:
            await close()
