"""Identity business logic: signup, login, sessions, organisation and member management.

Each public function is one unit of work: it commits its own transaction on success. On error
it raises an `AppError` and the request's session is rolled back.

Security events are logged with IDs only — never passwords or email addresses.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sia.core.config import Settings
from sia.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from sia.core.tenancy import set_tenant_context
from sia.modules.identity import policy, repository
from sia.modules.identity.models import (
    AuthSession,
    LoginAttempt,
    Membership,
    Organization,
    Role,
    User,
)
from sia.modules.identity.schemas import (
    MemberOut,
    MembershipOut,
    MeResponse,
    OrganizationOut,
    SignupRequest,
    UserOut,
)
from sia.modules.identity.security import (
    burn_password_check,
    hash_identifier,
    hash_password,
    hash_token,
    new_session_token,
    normalize_email,
    password_needs_rehash,
    verify_password,
)

logger = structlog.get_logger(__name__)

# Write `last_seen_at` at most this often, rather than on every request.
LAST_SEEN_RESOLUTION = timedelta(minutes=5)


# --- Errors ------------------------------------------------------------------------------------


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class EmailTakenError(ConflictError):
    code = "email_taken"

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class LoginThrottledError(TooManyRequestsError):
    code = "too_many_login_attempts"

    def __init__(self) -> None:
        super().__init__("Too many failed login attempts. Please try again later.")


class NoActiveOrganizationError(ForbiddenError):
    code = "no_active_organization"

    def __init__(self) -> None:
        super().__init__("Select an organization first.")


class LastOwnerError(ConflictError):
    code = "last_owner"

    def __init__(self) -> None:
        super().__init__("An organization must keep at least one owner.")


# --- Request context ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthContext:
    """The authenticated caller. `organization_id`/`role` are None if no organisation is active."""

    user: User
    session: AuthSession
    organization_id: uuid.UUID | None
    role: Role | None


@dataclass(frozen=True)
class TenantContext:
    """The authenticated caller acting inside an organisation."""

    user: User
    session: AuthSession
    organization_id: uuid.UUID
    role: Role


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class IssuedSession:
    token: str  # sent to the browser once, never stored
    session: AuthSession


def _now() -> datetime:
    return datetime.now(UTC)


def _violates(exc: IntegrityError, constraint: str) -> bool:
    """Whether an IntegrityError was caused by one specific named constraint."""
    driver_error = getattr(exc.orig, "__cause__", None)  # asyncpg's exception
    return getattr(driver_error, "constraint_name", None) == constraint


def _issue_session(
    db: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    client: ClientInfo,
) -> IssuedSession:
    token = new_session_token()
    session = AuthSession(
        id=uuid.uuid4(),
        token_hash=hash_token(token),
        user_id=user_id,
        active_organization_id=organization_id,
        expires_at=_now() + timedelta(hours=settings.session_absolute_timeout_hours),
        user_agent=(client.user_agent or "")[:512] or None,
        ip_address=client.ip_address,
    )
    db.add(session)
    return IssuedSession(token=token, session=session)


# --- Signup & login ----------------------------------------------------------------------------


async def signup(
    db: AsyncSession, settings: Settings, data: SignupRequest, client: ClientInfo
) -> tuple[MeResponse, IssuedSession]:
    email = normalize_email(data.email)
    if await repository.get_user_by_email(db, email):
        raise EmailTakenError()

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=await hash_password(data.password.get_secret_value()),
        name=data.name,
    )
    organization = Organization(id=uuid.uuid4(), name=data.organization_name)
    # Scope the transaction to the new organisation, so RLS permits creating it.
    await set_tenant_context(db, user_id=user.id, organization_id=organization.id)
    # Flush parents before children explicitly: the models have no relationship() links,
    # so SQLAlchemy does not infer insert order from the foreign keys.
    db.add_all([user, organization])
    try:
        await db.flush()
    except IntegrityError as exc:
        if _violates(exc, "uq_users_email"):  # concurrent signup with the same email
            raise EmailTakenError() from exc
        raise
    db.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.OWNER))
    issued = _issue_session(db, settings, user.id, organization.id, client)
    await db.commit()

    logger.info("signup_completed", user_id=str(user.id), organization_id=str(organization.id))
    org_out = OrganizationOut(id=organization.id, name=organization.name)
    me = MeResponse(
        user=UserOut(id=user.id, email=user.email, name=user.name),
        active_organization=org_out,
        role=Role.OWNER,
        memberships=[MembershipOut(organization=org_out, role=Role.OWNER)],
    )
    return me, issued


async def login(
    db: AsyncSession, settings: Settings, email: str, password: str, client: ClientInfo
) -> tuple[MeResponse, IssuedSession]:
    email = normalize_email(email)
    email_hash = hash_identifier(email)
    since = _now() - timedelta(minutes=settings.login_failure_window_minutes)

    by_email, by_ip = await repository.count_recent_login_failures(
        db, email_hash=email_hash, ip_address=client.ip_address, since=since
    )
    if (
        by_email >= settings.login_max_failures_per_email
        or by_ip >= settings.login_max_failures_per_ip
    ):
        logger.warning("login_throttled", ip_address=client.ip_address)
        raise LoginThrottledError()

    user = await repository.get_user_by_email(db, email)
    if user is None:
        await burn_password_check(password)  # same timing as a real check
        valid = False
    else:
        valid = await verify_password(user.password_hash, password) and user.is_active

    db.add(LoginAttempt(email_hash=email_hash, ip_address=client.ip_address, succeeded=valid))
    if not valid or user is None:
        await db.commit()  # persist the failure for throttling, then reject
        logger.info(
            "login_failed",
            reason="unknown_email" if user is None else "bad_password_or_inactive",
            user_id=str(user.id) if user else None,
            ip_address=client.ip_address,
        )
        raise InvalidCredentialsError()

    if password_needs_rehash(user.password_hash):
        user.password_hash = await hash_password(password)
    user.last_login_at = _now()

    await set_tenant_context(db, user_id=user.id, organization_id=None)
    organization_id = await repository.default_organization_for(db, user.id)
    issued = _issue_session(db, settings, user.id, organization_id, client)
    await db.commit()
    logger.info("login_succeeded", user_id=str(user.id), ip_address=client.ip_address)

    me = await build_me(db, user, issued.session)
    return me, issued


async def logout(db: AsyncSession, auth: AuthContext) -> None:
    auth.session.revoked_at = _now()
    await db.commit()
    logger.info("logout", user_id=str(auth.user.id))


# --- Session resolution (every authenticated request) ------------------------------------------


async def authenticate(db: AsyncSession, settings: Settings, token: str | None) -> AuthContext:
    if not token:
        raise UnauthorizedError("Authentication required.")

    now = _now()
    idle_cutoff = now - timedelta(hours=settings.session_idle_timeout_hours)
    found = await repository.get_active_session(
        db, hash_token(token), now=now, idle_cutoff=idle_cutoff
    )
    if found is None:
        raise UnauthorizedError("Your session has expired. Please log in again.")
    session, user = found

    if now - session.last_seen_at > LAST_SEEN_RESOLUTION:
        session.last_seen_at = now
        await db.commit()  # tenant context is set below, in the next transaction

    organization_id = session.active_organization_id
    await set_tenant_context(db, user_id=user.id, organization_id=organization_id)
    role: Role | None = None
    if organization_id is not None:
        membership = await repository.get_membership(db, organization_id, user.id)
        if membership is None:  # removed from the organisation since selecting it
            organization_id = None
            await set_tenant_context(db, user_id=user.id, organization_id=None)
        else:
            role = membership.role

    structlog.contextvars.bind_contextvars(
        user_id=str(user.id), organization_id=str(organization_id) if organization_id else None
    )
    return AuthContext(user=user, session=session, organization_id=organization_id, role=role)


def require_tenant(auth: AuthContext) -> TenantContext:
    if auth.organization_id is None or auth.role is None:
        raise NoActiveOrganizationError()
    return TenantContext(
        user=auth.user, session=auth.session, organization_id=auth.organization_id, role=auth.role
    )


# --- Current user & organisation ---------------------------------------------------------------


async def build_me(db: AsyncSession, user: User, session: AuthSession) -> MeResponse:
    await set_tenant_context(db, user_id=user.id, organization_id=session.active_organization_id)
    rows = await repository.list_user_memberships(db, user.id)
    memberships = [
        MembershipOut(organization=OrganizationOut(id=o.id, name=o.name), role=m.role)
        for m, o in rows
    ]
    active = next(
        (ms for ms in memberships if ms.organization.id == session.active_organization_id), None
    )
    return MeResponse(
        user=UserOut(id=user.id, email=user.email, name=user.name),
        active_organization=active.organization if active else None,
        role=active.role if active else None,
        memberships=memberships,
    )


async def switch_organization(
    db: AsyncSession, auth: AuthContext, organization_id: uuid.UUID
) -> MeResponse:
    # The caller's own memberships are readable in every organisation (RLS policy).
    if await repository.get_membership(db, organization_id, auth.user.id) is None:
        raise NotFoundError("Organization not found.")  # 404 either way: no existence leak
    auth.session.active_organization_id = organization_id
    await db.commit()
    logger.info("organization_switched", organization_id=str(organization_id))
    return await build_me(db, auth.user, auth.session)


async def get_organization(db: AsyncSession, tenant: TenantContext) -> OrganizationOut:
    organization = await repository.get_organization(db, tenant.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")
    return OrganizationOut(id=organization.id, name=organization.name)


async def rename_organization(
    db: AsyncSession, tenant: TenantContext, name: str
) -> OrganizationOut:
    organization = await repository.get_organization(db, tenant.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")
    organization.name = name
    await db.commit()
    logger.info("organization_renamed", organization_id=str(organization.id))
    return OrganizationOut(id=organization.id, name=name)


# --- Members -----------------------------------------------------------------------------------


async def list_members(db: AsyncSession, tenant: TenantContext) -> list[MemberOut]:
    rows = await repository.list_members(db, tenant.organization_id)
    return [
        MemberOut(user_id=u.id, name=u.name, email=u.email, role=m.role, joined_at=m.created_at)
        for m, u in rows
    ]


async def _target_membership(
    db: AsyncSession, tenant: TenantContext, user_id: uuid.UUID
) -> Membership:
    membership = await repository.get_membership(
        db, tenant.organization_id, user_id, for_update=True
    )
    if membership is None:
        raise NotFoundError("Member not found.")
    return membership


async def _ensure_another_owner_remains(db: AsyncSession, tenant: TenantContext) -> None:
    owners = await repository.lock_owner_memberships(db, tenant.organization_id)
    if len(owners) <= 1:
        raise LastOwnerError()


async def change_member_role(
    db: AsyncSession, tenant: TenantContext, user_id: uuid.UUID, new_role: Role
) -> None:
    target = await _target_membership(db, tenant, user_id)
    if not policy.can_change_role(tenant.role, target.role, new_role):
        raise ForbiddenError("You are not allowed to make this change.")
    if target.role == Role.OWNER and new_role != Role.OWNER:
        await _ensure_another_owner_remains(db, tenant)
    old_role, target.role = target.role, new_role
    await db.commit()
    logger.info(
        "member_role_changed",
        target_user_id=str(user_id),
        old_role=old_role.value,
        new_role=new_role.value,
    )


async def remove_member(db: AsyncSession, tenant: TenantContext, user_id: uuid.UUID) -> None:
    target = await _target_membership(db, tenant, user_id)
    is_self = user_id == tenant.user.id
    if not policy.can_remove_member(tenant.role, target.role, is_self=is_self):
        raise ForbiddenError("You are not allowed to remove this member.")
    if target.role == Role.OWNER:
        await _ensure_another_owner_remains(db, tenant)
    await db.delete(target)
    await db.commit()
    logger.info("member_removed", target_user_id=str(user_id), self_removal=is_self)
