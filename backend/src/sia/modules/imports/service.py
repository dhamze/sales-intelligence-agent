"""CSV import workflow: upload -> preview (nothing written) -> commit (one transaction).

Written as plain service functions with no HTTP concepts, so Phase 5 can run `commit_import`
from a background worker unchanged.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.errors import AppError, ConflictError, NotFoundError
from sia.core.pagination import (
    Page,
    SortSpec,
    build_page,
    decode_cursor,
    keyset_condition,
    order_by,
)
from sia.modules.companies import service as companies
from sia.modules.contacts import service as contacts
from sia.modules.identity.service import TenantContext
from sia.modules.imports import mapping as mapping_rules
from sia.modules.imports.mapping import ATTRIBUTES, FIELDS, EntityType, PreparedRows, RowError
from sia.modules.imports.models import Import, ImportStatus
from sia.modules.imports.parsing import ImportFileError, ParsedCsv, parse_csv
from sia.modules.imports.schemas import ImportOut, ImportPreview, RowErrorOut

logger = structlog.get_logger(__name__)

PREVIEW_TTL = timedelta(hours=24)
MAX_STORED_ERRORS = 500
MAX_PREVIEW_ERRORS = 50
SAMPLE_ROWS = 10


class InvalidImportFileError(AppError):
    status_code = 422
    code = "invalid_import_file"


class InvalidMappingError(AppError):
    status_code = 422
    code = "invalid_mapping"


class ImportNotPendingError(ConflictError):
    code = "import_not_pending"

    def __init__(self) -> None:
        super().__init__("This import has already been completed.")


class ImportExpiredError(ConflictError):
    code = "import_expired"

    def __init__(self) -> None:
        super().__init__("This preview has expired. Upload the file again.")


def _errors_out(errors: list[RowError], limit: int) -> list[dict[str, Any]]:
    return [{"row": e.row, "field": e.field, "message": e.message} for e in errors[:limit]]


def _to_out(record: Import) -> ImportOut:
    return ImportOut.model_validate(record, from_attributes=True)


def _parse(content: bytes) -> ParsedCsv:
    try:
        return parse_csv(content)
    except ImportFileError as exc:
        raise InvalidImportFileError(str(exc)) from exc


async def _link_contacts_to_companies(
    db: AsyncSession, tenant: TenantContext, prepared: PreparedRows
) -> None:
    domains = {r["company_domain"] for r in prepared.records if r.get("company_domain")}
    company_ids = await companies.company_ids_by_domain(db, tenant, domains)
    for record in prepared.records:
        domain = record.pop("company_domain", None)
        record["company_id"] = company_ids.get(domain) if domain else None


async def _existing_matches(
    db: AsyncSession, tenant: TenantContext, entity: EntityType, prepared: PreparedRows
) -> int:
    if entity == EntityType.COMPANIES:
        domains = {r["domain"] for r in prepared.records if r.get("domain")}
        return len(await companies.company_ids_by_domain(db, tenant, domains))
    emails = {r["email"] for r in prepared.records if r.get("email")}
    return len(await contacts.existing_emails(db, tenant, emails))


async def create_preview(
    db: AsyncSession,
    tenant: TenantContext,
    entity: EntityType,
    filename: str,
    content: bytes,
) -> ImportPreview:
    parsed = _parse(content)
    detected = mapping_rules.detect_mapping(parsed.headers, entity)
    prepared = mapping_rules.prepare_rows(parsed, detected, entity)
    existing = await _existing_matches(db, tenant, entity, prepared)

    record = Import(
        id=uuid.uuid4(),
        organization_id=tenant.organization_id,
        entity_type=entity,
        status=ImportStatus.PREVIEW,
        filename=(filename or "upload.csv")[:255],
        file_size=len(content),
        file_content=content,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        headers=parsed.headers,
        mapping=detected,
        row_count=len(parsed.rows),
        invalid_count=prepared.invalid_rows,
        duplicate_count=prepared.duplicate_rows,
        errors=_errors_out(prepared.errors, MAX_STORED_ERRORS),
        created_by_user_id=tenant.user.id,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    out = _to_out(record)
    await db.commit()
    logger.info("import_previewed", import_id=str(record.id), rows=record.row_count)

    available = FIELDS[entity] + ([ATTRIBUTES] if entity == EntityType.COMPANIES else [])
    return ImportPreview(
        **out.model_dump(exclude={"errors"}),
        errors=[RowErrorOut(**e) for e in record.errors[:MAX_PREVIEW_ERRORS]],
        available_fields=available,
        sample_rows=[
            dict(zip(parsed.headers, row, strict=True)) for row in parsed.rows[:SAMPLE_ROWS]
        ],
        valid_count=len(prepared.records),
        existing_matches=existing,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
    )


async def commit_import(
    db: AsyncSession,
    tenant: TenantContext,
    import_id: uuid.UUID,
    mapping_override: dict[str, str | None] | None,
) -> ImportOut:
    record = (
        await db.scalars(
            select(Import)
            .where(Import.organization_id == tenant.organization_id, Import.id == import_id)
            .with_for_update()  # two concurrent commits of the same preview: second one waits
        )
    ).one_or_none()
    if record is None:
        raise NotFoundError("Import not found.")
    if record.status != ImportStatus.PREVIEW or record.file_content is None:
        raise ImportNotPendingError()
    if datetime.now(UTC) - record.created_at > PREVIEW_TTL:
        raise ImportExpiredError()

    parsed = _parse(record.file_content)
    try:
        chosen = mapping_rules.validate_mapping(
            mapping_override if mapping_override is not None else record.mapping,
            parsed.headers,
            record.entity_type,
        )
    except mapping_rules.InvalidMappingError as exc:
        raise InvalidMappingError(str(exc)) from exc

    prepared = mapping_rules.prepare_rows(parsed, chosen, record.entity_type)
    for r in prepared.records:
        r.pop("_line", None)
    if record.entity_type == EntityType.COMPANIES:
        created, updated = await companies.import_companies(db, tenant, prepared.records)
    else:
        await _link_contacts_to_companies(db, tenant, prepared)
        created, updated = await contacts.import_contacts(db, tenant, prepared.records)

    record.mapping = chosen
    record.status = ImportStatus.COMPLETED
    record.file_content = None  # data minimisation: keep results, not the file
    record.created_count = created
    record.updated_count = updated
    record.unchanged_count = len(prepared.records) - created - updated
    record.invalid_count = prepared.invalid_rows
    record.duplicate_count = prepared.duplicate_rows
    record.errors = _errors_out(prepared.errors, MAX_STORED_ERRORS)
    record.completed_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(record)
    out = _to_out(record)
    await db.commit()
    logger.info(
        "import_completed",
        import_id=str(record.id),
        entity_type=record.entity_type.value,
        created=created,
        updated=updated,
        invalid=prepared.invalid_rows,
    )
    return out


async def get_import(db: AsyncSession, tenant: TenantContext, import_id: uuid.UUID) -> ImportOut:
    record = (
        await db.scalars(
            select(Import).where(
                Import.organization_id == tenant.organization_id, Import.id == import_id
            )
        )
    ).one_or_none()
    if record is None:
        raise NotFoundError("Import not found.")
    return _to_out(record)


_NEWEST_FIRST = SortSpec(
    key="-created_at", column=Import.created_at, descending=True, value_type=datetime
)


async def list_imports(
    db: AsyncSession, tenant: TenantContext, limit: int, cursor: str | None
) -> Page[ImportOut]:
    query = select(Import, Import.created_at).where(
        Import.organization_id == tenant.organization_id
    )
    if cursor:
        query = query.where(
            keyset_condition(_NEWEST_FIRST, Import.id, decode_cursor(cursor, _NEWEST_FIRST))
        )
    query = query.order_by(*order_by(_NEWEST_FIRST, Import.id)).limit(limit + 1)
    rows = [(record, created_at) for record, created_at in await db.execute(query)]
    return build_page(rows, limit, _NEWEST_FIRST, to_item=_to_out, get_id=lambda r: r.id)
