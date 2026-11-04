"""FastAPI dependencies for authentication and authorization.

Use these in route signatures:
    auth: CurrentAuth       -- any logged-in user
    tenant: CurrentTenant   -- logged in, with an active organisation (DB scoped to it)
    tenant: AdminTenant     -- as above, and role admin or owner
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from sia.core.config import Settings
from sia.core.db import DbSession
from sia.core.errors import ForbiddenError
from sia.modules.identity import policy, service
from sia.modules.identity.models import Role
from sia.modules.identity.service import AuthContext, ClientInfo, TenantContext


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_settings_from_app)]


def get_client_info(request: Request) -> ClientInfo:
    # Behind a reverse proxy, run uvicorn with --proxy-headers and --forwarded-allow-ips so that
    # request.client reflects the real client address (Phase 8 deployment).
    return ClientInfo(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


Client = Annotated[ClientInfo, Depends(get_client_info)]


async def get_auth_context(request: Request, db: DbSession, settings: AppSettings) -> AuthContext:
    token = request.cookies.get(settings.session_cookie_name)
    return await service.authenticate(db, settings, token)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


async def get_tenant_context(auth: CurrentAuth) -> TenantContext:
    return service.require_tenant(auth)


CurrentTenant = Annotated[TenantContext, Depends(get_tenant_context)]


def require_role(minimum: Role) -> Callable[[TenantContext], Awaitable[TenantContext]]:
    async def dependency(tenant: CurrentTenant) -> TenantContext:
        if not policy.has_at_least(tenant.role, minimum):
            raise ForbiddenError(f"This action requires the {minimum.value} role or higher.")
        return tenant

    return dependency


AdminTenant = Annotated[TenantContext, Depends(require_role(Role.ADMIN))]
