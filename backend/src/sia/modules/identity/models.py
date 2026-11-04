"""Identity tables.

Tenant isolation (see migration and docs/adr/0007):
- `organizations` and `memberships` are protected by Row-Level Security.
- `users`, `sessions` and `login_attempts` are not tenant-owned (a user can belong to several
  organisations; sessions are looked up before any organisation is known). They are only ever
  accessed through this module's repository.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    String,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from sia.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMAIL_MAX_LENGTH = 320  # RFC 5321 limit
NAME_MAX_LENGTH = 100


class Role(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are normalised to lower case before storage, so uniqueness is case-insensitive.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    last_login_at: Mapped[datetime | None]


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="membership_role",
            native_enum=False,  # VARCHAR + CHECK: adding a role later is a simple migration
            create_constraint=True,
            length=20,
            values_callable=lambda roles: [r.value for r in roles],
        )
    )


class AuthSession(UUIDPrimaryKeyMixin, Base):
    """A logged-in browser session. Only a SHA-256 hash of the token is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    active_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(INET)


class LoginAttempt(Base):
    """Login attempts, for brute-force throttling. Stores a hash of the email, not the email."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_hash_attempted_at", "email_hash", "attempted_at"),
        Index("ix_login_attempts_ip_address_attempted_at", "ip_address", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    email_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    ip_address: Mapped[str | None] = mapped_column(INET)
    succeeded: Mapped[bool]
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now())
