"""Authentication flows through the real API and database."""

import hashlib
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sia.core.config import Settings
from sia.main import create_app
from sia.modules.identity import repository
from tests.integration.conftest import ClientFactory

PASSWORD = "correct horse battery staple"
COOKIE = "sia_session"


async def signup(
    client: httpx.AsyncClient, email: str = "alice@example.com", org: str = "Acme"
) -> dict[str, Any]:
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Alice", "organization_name": org},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/auth/login", json={"email": email, "password": password})


# --- Signup ------------------------------------------------------------------------------------


async def test_signup_creates_user_org_owner_and_logs_in(client: httpx.AsyncClient) -> None:
    body = await signup(client, email="Alice@Example.COM")

    assert body["user"]["email"] == "alice@example.com"  # normalised
    assert body["role"] == "owner"
    assert body["active_organization"]["name"] == "Acme"
    assert client.cookies.get(COOKIE)

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == body


async def test_password_and_session_token_are_never_stored_in_plain_text(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await signup(client)
    token = client.cookies[COOKIE]

    async with owner_engine.connect() as conn:
        password_hash = await conn.scalar(text("SELECT password_hash FROM users"))
        token_hash = await conn.scalar(text("SELECT token_hash FROM sessions"))

    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash
    assert token_hash == hashlib.sha256(token.encode()).digest()


async def test_duplicate_email_is_rejected_case_insensitively(make_client: ClientFactory) -> None:
    await signup(make_client(), email="alice@example.com")

    response = await make_client().post(
        "/auth/signup",
        json={
            "email": "ALICE@example.com",
            "password": PASSWORD,
            "name": "Imposter",
            "organization_name": "Evil",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    ("override", "bad_field"),
    [
        ({"password": "short"}, "password"),
        ({"password": "x" * 129}, "password"),
        ({"email": "not-an-email"}, "email"),
        ({"name": "   "}, "name"),
        ({"is_admin": True}, "is_admin"),  # unexpected fields are rejected, not ignored
    ],
)
async def test_signup_validation(
    client: httpx.AsyncClient, override: dict[str, Any], bad_field: str
) -> None:
    payload = {
        "email": "a@example.com",
        "password": PASSWORD,
        "name": "A",
        "organization_name": "O",
    }
    response = await client.post("/auth/signup", json=payload | override)

    assert response.status_code == 422
    assert bad_field in {d["loc"][-1] for d in response.json()["error"]["details"]}


# --- Login -------------------------------------------------------------------------------------


async def test_login_failure_does_not_reveal_whether_email_exists(
    make_client: ClientFactory,
) -> None:
    await signup(make_client(), email="alice@example.com")
    client = make_client()

    wrong_password = await login(client, "alice@example.com", "wrong password 123")
    unknown_email = await login(client, "nobody@example.com", "wrong password 123")

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
        assert response.json()["error"]["message"] == "Invalid email or password."
    assert COOKIE not in client.cookies


async def test_login_issues_a_fresh_session_each_time(make_client: ClientFactory) -> None:
    laptop = make_client()
    await signup(laptop)
    phone = make_client()

    response = await login(phone, "ALICE@example.com")  # email is case-insensitive

    assert response.status_code == 200
    assert response.json()["active_organization"]["name"] == "Acme"
    assert phone.cookies[COOKIE] != laptop.cookies[COOKIE]
    assert (await laptop.get("/auth/me")).status_code == 200  # other device stays logged in
    assert (await phone.get("/auth/me")).status_code == 200


async def test_repeated_failures_lock_login_temporarily(make_client: ClientFactory) -> None:
    await signup(make_client())
    attacker = make_client()

    for _ in range(5):
        assert (await login(attacker, "alice@example.com", "guess-123456")).status_code == 401
    locked = await login(attacker, "alice@example.com")  # even the correct password

    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "too_many_login_attempts"


async def test_weak_password_hash_is_upgraded_on_login(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    await signup(client)
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET password_hash = :h"), {"h": weak})

    assert (await login(client, "alice@example.com")).status_code == 200

    async with owner_engine.connect() as conn:
        upgraded = await conn.scalar(text("SELECT password_hash FROM users"))
    assert upgraded != weak
    assert "m=65536" in upgraded


async def test_deactivated_user_cannot_log_in_or_use_existing_session(
    client: httpx.AsyncClient, make_client: ClientFactory, owner_engine: AsyncEngine
) -> None:
    await signup(client)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false"))

    assert (await client.get("/auth/me")).status_code == 401
    assert (await login(make_client(), "alice@example.com")).status_code == 401


# --- Sessions ----------------------------------------------------------------------------------


async def test_logout_revokes_the_session_server_side(
    client: httpx.AsyncClient, make_client: ClientFactory
) -> None:
    await signup(client)
    stolen_token = client.cookies[COOKIE]

    assert (await client.post("/auth/logout")).status_code == 204
    assert COOKIE not in client.cookies

    attacker = make_client()
    attacker.cookies.set(COOKIE, stolen_token)
    assert (await attacker.get("/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "expire_sql",
    [
        "UPDATE sessions SET expires_at = now() - interval '1 second'",  # absolute lifetime
        "UPDATE sessions SET last_seen_at = now() - interval '8 days'",  # idle timeout
        "UPDATE sessions SET revoked_at = now()",
    ],
)
async def test_expired_or_revoked_sessions_are_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, expire_sql: str
) -> None:
    await signup(client)
    async with owner_engine.begin() as conn:
        await conn.execute(text(expire_sql))

    response = await client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("token", ["", "garbage", "a" * 43])
async def test_forged_session_tokens_are_rejected(make_client: ClientFactory, token: str) -> None:
    attacker = make_client()
    attacker.cookies.set(COOKIE, token)

    assert (await attacker.get("/auth/me")).status_code == 401


async def test_concurrent_duplicate_signup_maps_to_email_taken(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two signups race past the "email exists?" check; the unique constraint must still win
    and the loser must get a clean 409, not a 500."""
    await signup(client, email="race@example.com")

    async def nobody(*_: object) -> None:
        return None

    monkeypatch.setattr(repository, "get_user_by_email", nobody)  # simulate losing the race
    response = await client.post(
        "/auth/signup",
        json={
            "email": "race@example.com",
            "password": PASSWORD,
            "name": "Racer",
            "organization_name": "Race Org",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_protected_endpoints_require_login(client: httpx.AsyncClient) -> None:
    for path in ("/auth/me", "/organizations/current", "/organizations/current/members"):
        assert (await client.get(path)).status_code == 401


# --- Browser security --------------------------------------------------------------------------


async def test_cookie_flags_in_development(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/signup",
        json={
            "email": "a@example.com",
            "password": PASSWORD,
            "name": "A",
            "organization_name": "O",
        },
    )
    cookie = response.headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie


async def test_cookie_flags_in_production(test_settings: Settings) -> None:
    app = create_app(test_settings.model_copy(update={"env": "production"}))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t") as client,
    ):
        response = await client.post(
            "/auth/signup",
            json={
                "email": "a@example.com",
                "password": PASSWORD,
                "name": "A",
                "organization_name": "O",
            },
        )
    cookie = response.headers["set-cookie"]

    assert cookie.startswith("__Host-sia_session=")
    assert "secure" in cookie.lower()
    assert "httponly" in cookie.lower()
    assert "domain" not in cookie.lower()  # required for the __Host- prefix


async def test_cross_site_login_attempt_is_blocked(client: httpx.AsyncClient) -> None:
    await signup(client)
    response = await client.post("/auth/logout", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert (await client.get("/auth/me")).status_code == 200  # still logged in
