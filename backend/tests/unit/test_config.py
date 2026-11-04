import pytest
from pydantic import ValidationError
from sqlalchemy import make_url

from sia.core.config import Settings
from tests.conftest import SettingsFactory


def test_database_url_is_built_from_parts(make_settings: SettingsFactory) -> None:
    url = make_settings(
        POSTGRES_HOST="db.internal", POSTGRES_PORT=6543, POSTGRES_DB="x"
    ).database_url

    assert url.drivername == "postgresql+asyncpg"
    assert (url.host, url.port, url.database, url.username) == ("db.internal", 6543, "x", "unit")


def test_password_with_special_characters_survives_url_round_trip(
    make_settings: SettingsFactory,
) -> None:
    password = "p@ss:w/rd#%?&="  # characters that would corrupt a hand-built URL string
    url = make_settings(POSTGRES_PASSWORD=password).database_url

    rendered = url.render_as_string(hide_password=False)

    assert make_url(rendered).password == password


def test_password_never_appears_in_repr_or_default_url_rendering(
    make_settings: SettingsFactory,
) -> None:
    settings = make_settings(POSTGRES_PASSWORD="super-secret-value")

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)
    assert "super-secret-value" not in str(settings.database_url)


def test_missing_required_value_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        Settings(_env_file=None, POSTGRES_USER="u")


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
    monkeypatch.setenv("POSTGRES_PASSWORD", "env-password")

    settings = Settings(_env_file=None)

    assert settings.is_production
    assert settings.postgres_user == "env-user"
