"""Contact business logic. Each write function is one unit of work and commits on success."""

import uuid
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.db import violates_constraint
from sia.core.errors import AppError, ConflictError, NotFoundError
from sia.core.pagination import Page, build_page, decode_cursor
from sia.modules.companies import service as companies
from sia.modules.companies.models import RecordSource
from sia.modules.contacts import repository
from sia.modules.contacts.models import Contact
from sia.modules.contacts.schemas import (
    ContactCreate,
    ContactListParams,
    ContactOut,
    ContactUpdate,
)
from sia.modules.identity.service import TenantContext

logger = structlog.get_logger(__name__)

EMAIL_UNIQUE = "uq_contacts_organization_id_email"
COMPANY_FK = "fk_contacts_company_same_org"
EMAIL_OR_NAME = "ck_contacts_has_email_or_name"


class ContactEmailTakenError(ConflictError):
    code = "contact_email_taken"

    def __init__(self, existing_id: uuid.UUID | None) -> None:
        super().__init__(
            "A contact with this email already exists.",
            details=[{"existing_contact_id": str(existing_id)}] if existing_id else None,
        )


class UnknownCompanyError(AppError):
    status_code = 422
    code = "company_not_found"

    def __init__(self) -> None:
        super().__init__("The referenced company does not exist.")


class ContactNeedsIdentityError(AppError):
    status_code = 422
    code = "contact_needs_email_or_name"

    def __init__(self) -> None:
        super().__init__("A contact needs an email address or a name.")


def _not_found() -> NotFoundError:
    return NotFoundError("Contact not found.")


async def list_contacts(
    db: AsyncSession, tenant: TenantContext, params: ContactListParams
) -> Page[ContactOut]:
    spec = repository.sort_spec(params)
    after = decode_cursor(params.cursor, spec) if params.cursor else None
    rows = await repository.list_contacts(db, tenant.organization_id, params, spec, after)
    return build_page(
        rows, params.limit, spec, to_item=ContactOut.model_validate, get_id=lambda c: c.id
    )


async def get_contact(db: AsyncSession, tenant: TenantContext, contact_id: uuid.UUID) -> ContactOut:
    contact = await repository.get(db, tenant.organization_id, contact_id)
    if contact is None:
        raise _not_found()
    return ContactOut.model_validate(contact)


async def _check_references(
    db: AsyncSession,
    tenant: TenantContext,
    *,
    company_id: uuid.UUID | None,
    email: str | None,
    except_id: uuid.UUID | None,
) -> None:
    # Company IDs from another tenant are invisible here (RLS), so they are simply "not found";
    # the composite foreign key would reject them anyway.
    if company_id is not None and not await companies.company_exists(db, tenant, company_id):
        raise UnknownCompanyError()
    if email is not None:
        existing = await repository.get_by_email(db, tenant.organization_id, email)
        if existing is not None and existing.id != except_id:
            raise ContactEmailTakenError(existing.id)


async def _flush(db: AsyncSession) -> None:
    """Translate expected constraint violations (races, invalid end states) into clean errors."""
    try:
        await db.flush()
    except IntegrityError as exc:
        if violates_constraint(exc, EMAIL_UNIQUE):
            raise ContactEmailTakenError(None) from exc
        if violates_constraint(exc, COMPANY_FK):
            raise UnknownCompanyError() from exc
        if violates_constraint(exc, EMAIL_OR_NAME):
            raise ContactNeedsIdentityError() from exc
        raise


async def create_contact(
    db: AsyncSession, tenant: TenantContext, data: ContactCreate
) -> ContactOut:
    await _check_references(
        db, tenant, company_id=data.company_id, email=data.email, except_id=None
    )
    contact = Contact(
        id=uuid.uuid4(),
        organization_id=tenant.organization_id,
        source=RecordSource.MANUAL,
        created_by_user_id=tenant.user.id,
        **data.model_dump(exclude_none=True),
    )
    db.add(contact)
    await _flush(db)
    await db.refresh(contact)  # load full_name and timestamps computed by the database
    out = ContactOut.model_validate(contact)
    await db.commit()
    logger.info("contact_created", contact_id=str(contact.id))
    return out


async def update_contact(
    db: AsyncSession, tenant: TenantContext, contact_id: uuid.UUID, data: ContactUpdate
) -> ContactOut:
    contact = await repository.get(db, tenant.organization_id, contact_id)
    if contact is None:
        raise _not_found()
    changes: dict[str, Any] = data.model_dump(exclude_unset=True)
    await _check_references(
        db,
        tenant,
        company_id=changes.get("company_id"),
        email=changes.get("email"),
        except_id=contact.id,
    )
    for field, value in changes.items():
        setattr(contact, field, value)
    await _flush(db)
    await db.refresh(contact)
    out = ContactOut.model_validate(contact)
    await db.commit()
    logger.info("contact_updated", contact_id=str(contact.id), fields=sorted(changes))
    return out


async def delete_contact(db: AsyncSession, tenant: TenantContext, contact_id: uuid.UUID) -> None:
    contact = await repository.get(db, tenant.organization_id, contact_id)
    if contact is None:
        raise _not_found()
    await db.delete(contact)
    await db.commit()
    logger.info("contact_deleted", contact_id=str(contact_id))
