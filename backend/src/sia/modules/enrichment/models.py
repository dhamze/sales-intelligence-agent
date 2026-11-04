"""Enrichment tables. All tenant-owned and RLS-protected; rows that belong to a company reference
it through the composite (organization_id, company_id) key, so they cannot cross tenants."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base, UUIDPrimaryKeyMixin


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _company_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["organization_id", "company_id"],
        ["companies.organization_id", "companies.id"],
        name=f"fk_{table}_company_same_org",
        ondelete="CASCADE",
    )


class EnrichmentRun(UUIDPrimaryKeyMixin, Base):
    """One request to enrich one company, and how it went."""

    __tablename__ = "enrichment_runs"
    __table_args__ = (
        _company_fk("enrichment_runs"),
        Index(
            "ix_enrichment_runs_org_company_created", "organization_id", "company_id", "created_at"
        ),
        Index("ix_enrichment_runs_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    company_id: Mapped[uuid.UUID]
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            name="enrichment_run_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda values: [v.value for v in values],
        )
    )
    failure_reason: Mapped[str | None] = mapped_column(String(50))
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class CompanyProfile(Base):
    """The latest verified AI profile of a company (facts with their evidence)."""

    __tablename__ = "company_profiles"
    __table_args__ = (_company_fk("company_profiles"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    facts_kept: Mapped[int] = mapped_column(Integer)
    facts_dropped: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WebPage(UUIDPrimaryKeyMixin, Base):
    """Text of a page read during enrichment: what the evidence quotes are checked against
    (and, later, what AI briefs are grounded in). Replaced on every re-enrichment."""

    __tablename__ = "web_pages"
    __table_args__ = (
        _company_fk("web_pages"),
        Index("ix_web_pages_org_company", "organization_id", "company_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    company_id: Mapped[uuid.UUID]
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime]
