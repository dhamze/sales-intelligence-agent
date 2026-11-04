"""Import records: one row per uploaded file. Tenant-owned and RLS-protected.

The uploaded bytes are kept only between preview and commit, then deleted (data minimisation);
the counts and row errors remain as an audit trail.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sia.modules.imports.mapping import EntityType


class ImportStatus(StrEnum):
    PREVIEW = "preview"
    COMPLETED = "completed"


def _enum(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda values: [v.value for v in values],
    )


class Import(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "imports"
    __table_args__ = (Index("ix_imports_org_created_at_id", "organization_id", "created_at", "id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "import_entity_type"))
    status: Mapped[ImportStatus] = mapped_column(_enum(ImportStatus, "import_status"))
    filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer)
    file_content: Mapped[bytes | None] = mapped_column(LargeBinary)  # cleared after commit
    encoding: Mapped[str] = mapped_column(String(20))
    delimiter: Mapped[str] = mapped_column(String(1))
    headers: Mapped[list[str]] = mapped_column(JSONB)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB)
    row_count: Mapped[int] = mapped_column(Integer)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    completed_at: Mapped[datetime | None]
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
