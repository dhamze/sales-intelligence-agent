"""Data access for contacts (explicit organisation filter + RLS)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ColumnElement,
    Float,
    and_,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.pagination import SortSpec, keyset_condition, order_by
from sia.core.search import escape_like, use_search_threshold
from sia.modules.companies.models import RecordSource
from sia.modules.contacts.models import Contact
from sia.modules.contacts.schemas import ContactListParams

_SORTS: dict[str, tuple[Any, bool, type]] = {
    "full_name": (Contact.full_name, False, str),
    "-full_name": (Contact.full_name, True, str),
    "created_at": (Contact.created_at, False, datetime),
    "-created_at": (Contact.created_at, True, datetime),
    "updated_at": (Contact.updated_at, False, datetime),
    "-updated_at": (Contact.updated_at, True, datetime),
}


def relevance(q: str) -> ColumnElement[float]:
    return cast(
        func.greatest(
            func.word_similarity(q, Contact.full_name),
            func.word_similarity(q, func.coalesce(Contact.email, "")),
        ),
        Float,
    )


def sort_spec(params: ContactListParams) -> SortSpec:
    key = params.sort or ("relevance" if params.q else "-created_at")
    if key == "relevance" and params.q:
        return SortSpec(key=key, column=relevance(params.q), descending=True, value_type=float)
    if key == "relevance":
        key = "-created_at"
    column, descending, value_type = _SORTS[key]
    return SortSpec(key=key, column=column, descending=descending, value_type=value_type)


def _conditions(organization_id: uuid.UUID, params: ContactListParams) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [Contact.organization_id == organization_id]
    if params.q:
        pattern = f"%{escape_like(params.q)}%"
        conditions.append(
            or_(
                literal(params.q).op("<%")(Contact.full_name),
                literal(params.q).op("<%")(Contact.email),
                Contact.full_name.ilike(pattern, escape="\\"),
                Contact.email.ilike(pattern, escape="\\"),
            )
        )
    if params.company_id is not None:
        conditions.append(Contact.company_id == params.company_id)
    if params.source is not None:
        conditions.append(Contact.source == params.source)
    return conditions


async def list_contacts(
    db: AsyncSession,
    organization_id: uuid.UUID,
    params: ContactListParams,
    spec: SortSpec,
    after: tuple[Any, uuid.UUID] | None,
) -> list[tuple[Contact, Any]]:
    if params.q:
        await use_search_threshold(db)
    query = select(Contact, spec.column.label("sort_value")).where(
        *_conditions(organization_id, params)
    )
    if after is not None:
        query = query.where(keyset_condition(spec, Contact.id, after))
    query = query.order_by(*order_by(spec, Contact.id)).limit(params.limit + 1)
    return [(contact, value) for contact, value in await db.execute(query)]


async def get(
    db: AsyncSession, organization_id: uuid.UUID, contact_id: uuid.UUID
) -> Contact | None:
    result = await db.scalars(
        select(Contact).where(Contact.organization_id == organization_id, Contact.id == contact_id)
    )
    return result.one_or_none()


async def get_by_email(db: AsyncSession, organization_id: uuid.UUID, email: str) -> Contact | None:
    result = await db.scalars(
        select(Contact).where(Contact.organization_id == organization_id, Contact.email == email)
    )
    return result.one_or_none()


# --- Bulk import -------------------------------------------------------------------------------

IMPORT_FILL_FIELDS = ("first_name", "last_name", "title", "phone", "linkedin_url", "company_id")
_IMPORT_COLUMNS = ("id", "email", *IMPORT_FILL_FIELDS)
_BATCH = 500


async def bulk_upsert(
    db: AsyncSession,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    records: list[dict[str, Any]],
) -> tuple[int, int]:
    """Insert new contacts; for an existing email, fill only its EMPTY fields.
    Returns (created, updated)."""
    created = updated = 0
    base = {
        "organization_id": organization_id,
        "source": RecordSource.IMPORT,
        "created_by_user_id": created_by,
    }
    for start in range(0, len(records), _BATCH):
        rows = [
            {**base, **{col: r.get(col) for col in _IMPORT_COLUMNS}}
            for r in records[start : start + _BATCH]
        ]
        insert_rows = pg_insert(Contact).values(rows)
        new = insert_rows.excluded
        upsert = insert_rows.on_conflict_do_update(
            constraint="uq_contacts_organization_id_email",
            set_={
                **{
                    f: func.coalesce(getattr(Contact, f), getattr(new, f))
                    for f in IMPORT_FILL_FIELDS
                },
                "updated_at": func.now(),
            },
            where=or_(
                *[
                    and_(getattr(Contact, f).is_(None), getattr(new, f).is_not(None))
                    for f in IMPORT_FILL_FIELDS
                ]
            ),
        ).returning(literal_column("xmax = 0", Boolean))
        for (inserted,) in await db.execute(upsert):
            if inserted:
                created += 1
            else:
                updated += 1
    return created, updated


async def existing_emails(
    db: AsyncSession, organization_id: uuid.UUID, emails: set[str]
) -> set[str]:
    if not emails:
        return set()
    rows = await db.scalars(
        select(Contact.email).where(
            Contact.organization_id == organization_id, Contact.email.in_(emails)
        )
    )
    return {email for email in rows if email}
