"""Request/response models for companies."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from sia.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from sia.core.schemas import (
    BlankToNone,
    OptionalLongText,
    OptionalShortText,
    OptionalUnboundedInput,
)
from sia.modules.companies.domains import InvalidDomainError, normalize_domain, normalize_url
from sia.modules.companies.models import (
    COMPANY_NAME_MAX,
    RecordSource,
)
from sia.modules.scoring.engine import Tier, tier_for

MAX_ATTRIBUTES = 100
MAX_EMPLOYEES = 10_000_000


# Range applies to the int member only (a constraint on `int | None` would also hit None).
OptionalEmployeeCount = Annotated[Annotated[int, Field(ge=0, le=MAX_EMPLOYEES)] | None, BlankToNone]
AttributeValue = str | int | float | bool | None


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _CompanyFields(_Request):
    domain: OptionalUnboundedInput = None
    website: OptionalUnboundedInput = None
    industry: OptionalShortText = None
    employee_count: OptionalEmployeeCount = None
    country: OptionalShortText = None
    city: OptionalShortText = None
    description: OptionalLongText = None
    attributes: dict[str, AttributeValue] | None = None

    @field_validator("domain")
    @classmethod
    def _domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_domain(value)
        except InvalidDomainError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("website")
    @classmethod
    def _website(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_url(value)
        except InvalidDomainError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("attributes")
    @classmethod
    def _attributes(
        cls, value: dict[str, AttributeValue] | None
    ) -> dict[str, AttributeValue] | None:
        if value is not None and len(value) > MAX_ATTRIBUTES:
            raise ValueError(f"At most {MAX_ATTRIBUTES} attributes are allowed.")
        return value


class CompanyCreate(_CompanyFields):
    name: str = Field(min_length=1, max_length=COMPANY_NAME_MAX)

    @model_validator(mode="after")
    def _derive_domain(self) -> "CompanyCreate":
        # "acme.com" is the dedupe key: derive it from the website when not given explicitly.
        if self.domain is None and self.website is not None:
            self.domain = normalize_domain(self.website)
        return self


class CompanyUpdate(_CompanyFields):
    """PATCH: only fields present in the request change; an explicit null clears a field."""

    name: str | None = Field(default=None, min_length=1, max_length=COMPANY_NAME_MAX)

    @model_validator(mode="after")
    def _name_not_null(self) -> "CompanyUpdate":
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be empty.")
        return self


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    domain: str | None
    website: str | None
    industry: str | None
    employee_count: int | None
    country: str | None
    city: str | None
    description: str | None
    attributes: dict[str, Any]
    source: RecordSource
    icp_score: int | None = Field(description="ICP fit 0-100; null when not scored or no ICP")
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icp_tier(self) -> Tier | None:
        return tier_for(self.icp_score) if self.icp_score is not None else None


class FacetValue(BaseModel):
    value: str
    count: int


class CompanyFacets(BaseModel):
    """Values available for filtering, most common first (for filter dropdowns)."""

    industries: list[FacetValue]
    countries: list[FacetValue]


CompanySort = Literal[
    "name",
    "-name",
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
    "icp_score",
    "-icp_score",
    "relevance",
]


class CompanyListParams(BaseModel):
    """Query string for GET /companies. Repeat a list parameter to match any value:
    ?industry=Software&industry=Fintech"""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200, description="Fuzzy search on name/domain")
    industry: list[str] = Field(default_factory=list, max_length=20)
    country: list[str] = Field(default_factory=list, max_length=20)
    employees_min: int | None = Field(default=None, ge=0)
    employees_max: int | None = Field(default=None, ge=0)
    source: RecordSource | None = None
    tier: list[Tier] = Field(default_factory=list, max_length=4, description="ICP fit tiers")
    created_after: datetime | None = None
    created_before: datetime | None = None
    sort: CompanySort | None = Field(
        default=None, description="Default: relevance when searching, otherwise -created_at"
    )
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = None

    @field_validator("q")
    @classmethod
    def _q(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None
