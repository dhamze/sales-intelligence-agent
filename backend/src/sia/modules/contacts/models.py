"""Contact table. Tenant-owned: RLS-protected (see migration and docs/adr/0007)."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sia.modules.companies.models import RecordSource, source_column

PERSON_NAME_MAX = 100


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        # Composite foreign key: a contact can only reference a company in the SAME
        # organisation. Foreign-key checks deliberately bypass RLS, so a plain FK on
        # company_id alone would let a guessed ID link across tenants.
        # When the company is deleted, only company_id is cleared (organization_id stays).
        ForeignKeyConstraint(
            ["organization_id", "company_id"],
            ["companies.organization_id", "companies.id"],
            name="fk_contacts_company_same_org",
            ondelete="SET NULL (company_id)",
        ),
        UniqueConstraint("organization_id", "email"),
        CheckConstraint("email IS NOT NULL OR full_name <> ''", name="has_email_or_name"),
        Index("ix_contacts_org_company_id", "organization_id", "company_id"),
        Index("ix_contacts_org_full_name_id", "organization_id", "full_name", "id"),
        Index("ix_contacts_org_created_at_id", "organization_id", "created_at", "id"),
        Index("ix_contacts_org_updated_at_id", "organization_id", "updated_at", "id"),
        Index(
            "ix_contacts_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_contacts_email_trgm",
            "email",
            postgresql_using="gin",
            postgresql_ops={"email": "gin_trgm_ops"},
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    company_id: Mapped[uuid.UUID | None]
    first_name: Mapped[str | None] = mapped_column(String(PERSON_NAME_MAX))
    last_name: Mapped[str | None] = mapped_column(String(PERSON_NAME_MAX))
    # Maintained by PostgreSQL: always consistent, and sortable/searchable with an index.
    full_name: Mapped[str] = mapped_column(
        String(2 * PERSON_NAME_MAX + 1),
        Computed(
            "btrim(coalesce(first_name, '') || ' ' || coalesce(last_name, ''))", persisted=True
        ),
    )
    email: Mapped[str | None] = mapped_column(String(320))
    title: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    linkedin_url: Mapped[str | None] = mapped_column(String(2048))
    source: Mapped[RecordSource] = source_column()
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
