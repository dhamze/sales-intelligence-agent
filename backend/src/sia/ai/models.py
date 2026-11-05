"""Log of every AI call: what it cost, how long it took and how it ended. Tenant-owned (RLS)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from sia.ai.client import Outcome
from sia.core.db import Base, UUIDPrimaryKeyMixin


class AIGeneration(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_generations"
    __table_args__ = (Index("ix_ai_generations_org_created_at", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    purpose: Mapped[str] = mapped_column(String(50))  # e.g. "company_profile"
    subject_id: Mapped[uuid.UUID | None]  # what it was about (e.g. the company)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    outcome: Mapped[Outcome] = mapped_column(
        Enum(
            Outcome,
            name="ai_outcome",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda values: [v.value for v in values],
        )
    )
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(100))
    stop_reason: Mapped[str | None] = mapped_column(String(50))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AISpendDay(Base):
    """Estimated AI spend per day across the whole installation, for the monthly budget.

    Deliberately has no organisation column: it holds only totals, so checking the budget never
    needs to read other tenants' rows (which RLS forbids anyway).
    """

    __tablename__ = "ai_spend_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
