"""Worker tasks for scoring."""

import uuid

from sia.modules.scoring import service
from sia.worker import app
from sia.worker.runtime import tenant_session


@app.task(name=service.TASK_NAME, queue=service.QUEUE)
async def rescore_organization(organization_id: str) -> None:
    org = uuid.UUID(organization_id)
    async with tenant_session(organization_id=org) as db:
        await service.rescore_organization(db, org)
