"""HTTP routes for contacts (thin: parse, call service, respond)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from sia.core.db import DbSession
from sia.core.pagination import Page
from sia.modules.contacts import service
from sia.modules.contacts.schemas import (
    ContactCreate,
    ContactListParams,
    ContactOut,
    ContactUpdate,
)
from sia.modules.identity.dependencies import AdminTenant, CurrentTenant

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("")
async def list_contacts(
    params: Annotated[ContactListParams, Query()], tenant: CurrentTenant, db: DbSession
) -> Page[ContactOut]:
    return await service.list_contacts(db, tenant, params)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_contact(body: ContactCreate, tenant: CurrentTenant, db: DbSession) -> ContactOut:
    return await service.create_contact(db, tenant, body)


@router.get("/{contact_id}")
async def get_contact(contact_id: uuid.UUID, tenant: CurrentTenant, db: DbSession) -> ContactOut:
    return await service.get_contact(db, tenant, contact_id)


@router.patch("/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID, body: ContactUpdate, tenant: CurrentTenant, db: DbSession
) -> ContactOut:
    return await service.update_contact(db, tenant, contact_id, body)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: uuid.UUID, tenant: AdminTenant, db: DbSession) -> None:
    await service.delete_contact(db, tenant, contact_id)
