"""Data access for the identity module. The only place that queries identity tables.

Queries on `organizations` and `memberships` are additionally filtered by Row-Level Security
in the database; the explicit organisation filters here are the first of two layers.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sia.modules.identity.models import (
    AuthSession,
    LoginAttempt,
    Membership,
    Organization,
    Role,
    User,
)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.scalars(select(User).where(User.email == email))
    return result.one_or_none()


async def get_active_session(
    db: AsyncSession, token_hash: bytes, *, now: datetime, idle_cutoff: datetime
) -> tuple[AuthSession, User] | None:
    result = await db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            AuthSession.last_seen_at > idle_cutoff,
            User.is_active.is_(True),
        )
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row else None


async def get_membership(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
) -> Membership | None:
    query = select(Membership).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id
    )
    if for_update:
        query = query.with_for_update()
    return (await db.scalars(query)).one_or_none()


async def get_organization(db: AsyncSession, organization_id: uuid.UUID) -> Organization | None:
    return await db.get(Organization, organization_id)


async def list_user_memberships(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Membership, Organization]]:
    result = await db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.name, Organization.id)
    )
    return [(m, o) for m, o in result]


async def default_organization_for(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """The organisation a fresh login starts in: the one the user joined most recently."""
    result = await db.scalars(
        select(Membership.organization_id)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at.desc())
        .limit(1)
    )
    return result.one_or_none()


async def list_members(
    db: AsyncSession, organization_id: uuid.UUID
) -> list[tuple[Membership, User]]:
    result = await db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
        .order_by(User.name, User.id)
    )
    return [(m, u) for m, u in result]


async def lock_owner_memberships(db: AsyncSession, organization_id: uuid.UUID) -> list[Membership]:
    """Lock the owner rows, so two concurrent requests cannot both remove the last owner."""
    result = await db.scalars(
        select(Membership)
        .where(Membership.organization_id == organization_id, Membership.role == Role.OWNER)
        .with_for_update()
    )
    return list(result)


async def count_recent_login_failures(
    db: AsyncSession, *, email_hash: bytes, ip_address: str | None, since: datetime
) -> tuple[int, int]:
    """Failed attempts since `since`, by email and by IP address."""
    failed_since = (LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at > since)
    by_email = await db.scalar(
        select(func.count()).where(LoginAttempt.email_hash == email_hash, *failed_since)
    )
    by_ip = 0
    if ip_address:
        by_ip = (
            await db.scalar(
                select(func.count()).where(LoginAttempt.ip_address == ip_address, *failed_since)
            )
        ) or 0
    return by_email or 0, by_ip
