"""Insights tables. Tenant-owned and RLS-protected; rows reference their company through the
composite (organization_id, company_id) key, so they cannot cross tenants."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base, UUIDPrimaryKeyMixin
from sia.modules.enrichment.models import RunStatus


def _company_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["organization_id", "company_id"],
        ["companies.organization_id", "companies.id"],
        name=f"fk_{table}_company_same_org",
        ondelete="CASCADE",
    )


class BriefRun(UUIDPrimaryKeyMixin, Base):
    """One request to write a company's brief, and how it went (also counts toward the cap)."""

    __tablename__ = "brief_runs"
    __table_args__ = (
        _company_fk("brief_runs"),
        Index("ix_brief_runs_org_company_created", "organization_id", "company_id", "created_at"),
        Index("ix_brief_runs_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    company_id: Mapped[uuid.UUID]
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            name="brief_run_status",
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


class AccountBrief(Base):
    """The latest verified brief of a company."""

    __tablename__ = "account_briefs"
    __table_args__ = (_company_fk("account_briefs"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)  # verified BriefOutput shape
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # id, kind, title, url
    claims_kept: Mapped[int] = mapped_column(Integer)
    claims_dropped: Mapped[int] = mapped_column(Integer)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now())
