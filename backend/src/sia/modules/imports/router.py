"""HTTP routes for CSV imports (thin: parse, call service, respond)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from sia.core.db import DbSession
from sia.core.errors import AppError
from sia.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from sia.modules.identity.dependencies import CurrentTenant
from sia.modules.imports import service
from sia.modules.imports.mapping import EntityType
from sia.modules.imports.parsing import MAX_FILE_BYTES
from sia.modules.imports.schemas import CommitImportRequest, ImportOut, ImportPreview

router = APIRouter(prefix="/imports", tags=["imports"])


class FileTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    file: Annotated[UploadFile, File(description="CSV file (max 5 MB, 10,000 rows)")],
    entity_type: Annotated[EntityType, Form()],
    tenant: CurrentTenant,
    db: DbSession,
) -> ImportPreview:
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise FileTooLargeError(f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    return await service.create_preview(db, tenant, entity_type, file.filename or "", content)


@router.post("/{import_id}/commit")
async def commit(
    import_id: uuid.UUID, body: CommitImportRequest, tenant: CurrentTenant, db: DbSession
) -> ImportOut:
    return await service.commit_import(db, tenant, import_id, body.mapping)


@router.get("")
async def list_imports(
    tenant: CurrentTenant,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Page[ImportOut]:
    return await service.list_imports(db, tenant, limit, cursor)


@router.get("/{import_id}")
async def get_import(import_id: uuid.UUID, tenant: CurrentTenant, db: DbSession) -> ImportOut:
    return await service.get_import(db, tenant, import_id)
