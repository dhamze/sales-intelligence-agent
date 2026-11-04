"""HTTP routes for authentication and organisation management (thin: parse, call, respond)."""

import uuid

from fastapi import APIRouter, Response, status

from sia.core.config import Settings
from sia.core.db import DbSession
from sia.modules.identity import service
from sia.modules.identity.dependencies import (
    AdminTenant,
    AppSettings,
    Client,
    CurrentAuth,
    CurrentTenant,
)
from sia.modules.identity.schemas import (
    LoginRequest,
    MemberOut,
    MeResponse,
    OrganizationOut,
    SignupRequest,
    SwitchOrganizationRequest,
    UpdateMemberRequest,
    UpdateOrganizationRequest,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
org_router = APIRouter(prefix="/organizations", tags=["organizations"])


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_absolute_timeout_hours * 3600,
        path="/",
        httponly=True,  # JavaScript cannot read it, so XSS cannot steal the session
        secure=settings.session_cookie_secure,
        samesite="lax",  # not sent on cross-site POSTs (first line of CSRF defence)
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


# --- /auth -------------------------------------------------------------------------------------


@auth_router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest, response: Response, db: DbSession, settings: AppSettings, client: Client
) -> MeResponse:
    me, issued = await service.signup(db, settings, body, client)
    _set_session_cookie(response, settings, issued.token)
    return me


@auth_router.post("/login")
async def login(
    body: LoginRequest, response: Response, db: DbSession, settings: AppSettings, client: Client
) -> MeResponse:
    me, issued = await service.login(
        db, settings, body.email, body.password.get_secret_value(), client
    )
    _set_session_cookie(response, settings, issued.token)
    return me


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    auth: CurrentAuth, response: Response, db: DbSession, settings: AppSettings
) -> None:
    await service.logout(db, auth)
    _clear_session_cookie(response, settings)


@auth_router.get("/me")
async def me(auth: CurrentAuth, db: DbSession) -> MeResponse:
    return await service.build_me(db, auth.user, auth.session)


@auth_router.put("/session/organization")
async def switch_organization(
    body: SwitchOrganizationRequest, auth: CurrentAuth, db: DbSession
) -> MeResponse:
    return await service.switch_organization(db, auth, body.organization_id)


# --- /organizations ----------------------------------------------------------------------------


@org_router.get("/current")
async def get_current_organization(tenant: CurrentTenant, db: DbSession) -> OrganizationOut:
    return await service.get_organization(db, tenant)


@org_router.patch("/current")
async def rename_current_organization(
    body: UpdateOrganizationRequest, tenant: AdminTenant, db: DbSession
) -> OrganizationOut:
    return await service.rename_organization(db, tenant, body.name)


@org_router.get("/current/members")
async def list_members(tenant: CurrentTenant, db: DbSession) -> list[MemberOut]:
    return await service.list_members(db, tenant)


@org_router.patch("/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def change_member_role(
    user_id: uuid.UUID, body: UpdateMemberRequest, tenant: CurrentTenant, db: DbSession
) -> None:
    await service.change_member_role(db, tenant, user_id, body.role)


@org_router.delete("/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: uuid.UUID, tenant: CurrentTenant, db: DbSession) -> None:
    await service.remove_member(db, tenant, user_id)
