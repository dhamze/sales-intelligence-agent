"""Request/response models for contacts."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from sia.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from sia.core.schemas import (
    BlankToNone,
    OptionalMediumText,
    OptionalShortText,
    OptionalTinyText,
    OptionalUnboundedInput,
)
from sia.modules.companies.domains import InvalidDomainError, normalize_url
from sia.modules.companies.models import RecordSource

_PHONE = re.compile(r"^[0-9+().\-\s/x]{3,50}$")


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _ContactFields(_Request):
    company_id: uuid.UUID | None = None
    first_name: OptionalShortText = None
    last_name: OptionalShortText = None
    email: Annotated[EmailStr | None, BlankToNone] = None
    title: OptionalMediumText = None
    phone: OptionalTinyText = None
    linkedin_url: OptionalUnboundedInput = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if value is not None and not _PHONE.match(value):
            raise ValueError("Not a valid phone number.")
        return value

    @field_validator("linkedin_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_url(value)
        except InvalidDomainError as exc:
            raise ValueError(str(exc)) from exc


class ContactCreate(_ContactFields):
    @model_validator(mode="after")
    def _identifiable(self) -> "ContactCreate":
        if not (self.email or self.first_name or self.last_name):
            raise ValueError("A contact needs an email address or a name.")
        return self


class ContactUpdate(_ContactFields):
    """PATCH: only fields present in the request change; an explicit null clears a field.
    (The database rejects updates that would leave a contact with neither email nor name.)"""


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID | None
    first_name: str | None
    last_name: str | None
    full_name: str
    email: str | None
    title: str | None
    phone: str | None
    linkedin_url: str | None
    source: RecordSource
    created_at: datetime
    updated_at: datetime


ContactSort = Literal[
    "full_name", "-full_name", "created_at", "-created_at", "updated_at", "-updated_at", "relevance"
]


class ContactListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200, description="Fuzzy search on name/email")
    company_id: uuid.UUID | None = None
    source: RecordSource | None = None
    sort: ContactSort | None = None
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = None

    @field_validator("q")
    @classmethod
    def _q(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None
