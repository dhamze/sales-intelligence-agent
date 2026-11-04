from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import make_url

from sia.core.config import APP_DB_ROLE, Settings
from tests.conftest import PRODUCTION, SettingsFactory


def test_runtime_url_uses_restricted_app_role(make_settings: SettingsFactory) -> None:
    url = make_settings(
        POSTGRES_HOST="db.internal", POSTGRES_PORT=6543, POSTGRES_DB="x"
    ).database_url

    assert url.drivername == "postgresql+asyncpg"
    assert (url.host, url.port, url.database) == ("db.internal", 6543, "x")
    assert url.username == APP_DB_ROLE
    assert url.password == "unit-app-password"


def test_migration_url_uses_owner_role(make_settings: SettingsFactory) -> None:
    url = make_settings().migration_database_url

    assert (url.username, url.password) == ("unit", "unit-password")


@pytest.mark.parametrize("variable", ["POSTGRES_PASSWORD", "SIA_APP_DB_PASSWORD"])
def test_passwords_with_special_characters_survive_url_round_trip(
    make_settings: SettingsFactory, variable: str
) -> None:
    password = "p@ss:w/rd#%?&="  # characters that would corrupt a hand-built URL string
    settings = make_settings(**{variable: password})

    rendered = {
        make_url(url.render_as_string(hide_password=False)).password
        for url in (settings.database_url, settings.migration_database_url)
    }

    assert password in rendered


def test_passwords_never_appear_in_repr_or_default_url_rendering(
    make_settings: SettingsFactory,
) -> None:
    settings = make_settings(POSTGRES_PASSWORD="owner-secret", SIA_APP_DB_PASSWORD="app-secret")

    for text in (
        repr(settings),
        str(settings),
        str(settings.database_url),
        str(settings.migration_database_url),
    ):
        assert "owner-secret" not in text
        assert "app-secret" not in text


@pytest.mark.parametrize("missing", ["POSTGRES_PASSWORD", "SIA_APP_DB_PASSWORD"])
def test_missing_required_value_fails_fast(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    values: dict[str, Any] = {
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "p",
        "SIA_APP_DB_PASSWORD": "a",
    }
    del values[missing]
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(ValidationError, match=missing):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("variable", "value"),
    [("SIA_ENV", "staging"), ("SIA_LOG_FORMAT", "xml"), ("POSTGRES_PORT", 70000)],
)
def test_invalid_values_are_rejected(
    make_settings: SettingsFactory, variable: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{variable: value})


def test_values_are_read_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIA_ENV", "production")
    monkeypatch.setenv("POSTGRES_USER", "env-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env-password-long-and-random-1234")
    monkeypatch.setenv("SIA_APP_DB_PASSWORD", "env-app-password-long-and-random-1")
    monkeypatch.setenv("SIA_ALLOWED_ORIGINS", '["https://sia.example.com"]')

    settings = Settings(_env_file=None)

    assert settings.is_production
    assert settings.postgres_user == "env-user"
    assert settings.app_db_password.get_secret_value() == "env-app-password-long-and-random-1"
    assert settings.allowed_origins == ["https://sia.example.com"]


@pytest.mark.parametrize(
    "override",
    [
        {"SIA_ALLOWED_ORIGINS": ["http://sia.example.com"]},  # not HTTPS
        {"SIA_ALLOWED_ORIGINS": []},
        {"POSTGRES_PASSWORD": "short"},
        {"SIA_APP_DB_PASSWORD": "change-me-too-change-me-too-change-me"},  # the example value
    ],
)
def test_unsafe_production_settings_refuse_to_start(
    make_settings: SettingsFactory, override: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError, match="In production"):
        make_settings(**(PRODUCTION | override))


def test_local_settings_are_not_held_to_production_rules(make_settings: SettingsFactory) -> None:
    settings = make_settings(POSTGRES_PASSWORD="short", SIA_ALLOWED_ORIGINS=["http://x"])
    assert not settings.is_production
