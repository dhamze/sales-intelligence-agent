"""Company table. Tenant-owned: RLS-protected (see migration and docs/adr/0007)."""

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

COMPANY_NAME_MAX = 200
SHORT_TEXT_MAX = 100
DESCRIPTION_MAX = 5000


class RecordSource(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"


def source_column() -> Mapped[RecordSource]:
    return mapped_column(
        Enum(
            RecordSource,
            name="record_source",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda values: [v.value for v in values],
        )
    )


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        # One company per domain per organisation (the de-duplication key). NULLs don't clash.
        UniqueConstraint("organization_id", "domain"),
        # Target for contacts' composite foreign key, which keeps links within one tenant.
        UniqueConstraint("organization_id", "id"),
        CheckConstraint("employee_count >= 0", name="employee_count_non_negative"),
        # Keyset pagination: one index per sort order, organisation first.
        Index("ix_companies_org_name_id", "organization_id", "name", "id"),
        Index("ix_companies_org_created_at_id", "organization_id", "created_at", "id"),
        Index("ix_companies_org_updated_at_id", "organization_id", "updated_at", "id"),
        # Sorting/filtering by ICP fit; unscored companies (NULL) sort as -1, i.e. last.
        Index(
            "ix_companies_org_icp_score_id",
            "organization_id",
            text("coalesce(icp_score, -1)"),
            "id",
        ),
        CheckConstraint("icp_score BETWEEN 0 AND 100", name="icp_score_range"),
        # Fuzzy search (pg_trgm): typo-tolerant matching on name and domain.
        Index(
            "ix_companies_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_companies_domain_trgm",
            "domain",
            postgresql_using="gin",
            postgresql_ops={"domain": "gin_trgm_ops"},
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(COMPANY_NAME_MAX))
    domain: Mapped[str | None] = mapped_column(String(253))
    website: Mapped[str | None] = mapped_column(String(2048))
    industry: Mapped[str | None] = mapped_column(String(SHORT_TEXT_MAX))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str | None] = mapped_column(String(SHORT_TEXT_MAX))
    city: Mapped[str | None] = mapped_column(String(SHORT_TEXT_MAX))
    description: Mapped[str | None] = mapped_column(Text)
    # Extra fields from imports (unknown CSV columns), so no customer data is silently dropped.
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    source: Mapped[RecordSource] = source_column()
    # ICP fit 0-100, copied from company_scores for fast list sorting/filtering. Written only by
    # repository.set_icp_scores() (scoring keeps it in sync); NULL = not scored / no ICP.
    icp_score: Mapped[int | None] = mapped_column(SmallInteger)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
