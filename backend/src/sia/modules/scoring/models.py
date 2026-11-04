"""Scoring tables. Tenant-owned and RLS-protected; scores reference their company through the
composite (organization_id, company_id) key, so they cannot cross tenants."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    SmallInteger,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base


class ICPProfile(Base):
    """The organisation's ideal customer profile (one per organisation). `version` goes up on
    every change, so each stored score says which definition produced it."""

    __tablename__ = "icp_profiles"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)  # validated ICPDefinition
    version: Mapped[int] = mapped_column(Integer)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CompanyScore(Base):
    """A company's latest score, with the per-criterion breakdown that explains it."""

    __tablename__ = "company_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "company_id"],
            ["companies.organization_id", "companies.id"],
            name="fk_company_scores_company_same_org",
            ondelete="CASCADE",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    score: Mapped[int] = mapped_column(SmallInteger)
    disqualified: Mapped[bool] = mapped_column(Boolean)
    completeness: Mapped[float] = mapped_column(Numeric(3, 2, asdecimal=False))
    breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    icp_version: Mapped[int] = mapped_column(Integer)
    scored_at: Mapped[datetime] = mapped_column(server_default=func.now())
