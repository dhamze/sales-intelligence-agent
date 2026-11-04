"""Application configuration, loaded from environment variables (and `.env` in development).

All settings are validated at startup: a missing or malformed value stops the app immediately
with a clear error, instead of failing later in some unrelated code path.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["console", "json"]

# The restricted database role the application connects as. Fixed (not configurable) because
# migrations grant privileges to it by name. Created by infra/postgres/init/02-create-app-role.sh.
APP_DB_ROLE = "sia_app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds values for other tools (e.g. Docker Compose)
        frozen=True,
    )

    # --- Application ---
    env: Environment = Field(default="development", validation_alias="SIA_ENV")
    log_level: LogLevel = Field(default="INFO", validation_alias="SIA_LOG_LEVEL")
    log_format: LogFormat = Field(default="console", validation_alias="SIA_LOG_FORMAT")

    # --- Database ---
    postgres_host: str = Field(default="127.0.0.1", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="sia_dev", validation_alias="POSTGRES_DB")
    # Owner role: owns the schema and runs migrations. Never used by the running API.
    postgres_user: str = Field(validation_alias="POSTGRES_USER")
    # SecretStr keeps passwords out of logs, tracebacks and `repr()` output.
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    # Password for the restricted runtime role APP_DB_ROLE (see docs/adr/0007).
    app_db_password: SecretStr = Field(validation_alias="SIA_APP_DB_PASSWORD")
    db_pool_size: int = Field(default=5, ge=1, validation_alias="SIA_DB_POOL_SIZE")
    db_connect_timeout_seconds: float = Field(
        default=5.0, gt=0, validation_alias="SIA_DB_CONNECT_TIMEOUT_SECONDS"
    )

    # --- Background worker ---
    worker_concurrency: int = Field(
        default=4, ge=1, le=32, validation_alias="SIA_WORKER_CONCURRENCY"
    )

    # --- Authentication & browser security ---
    session_idle_timeout_hours: int = Field(
        default=24 * 7, ge=1, validation_alias="SIA_SESSION_IDLE_TIMEOUT_HOURS"
    )
    session_absolute_timeout_hours: int = Field(
        default=24 * 30, ge=1, validation_alias="SIA_SESSION_ABSOLUTE_TIMEOUT_HOURS"
    )
    # Browser origins allowed to make state-changing requests (CSRF protection).
    allowed_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
        validation_alias="SIA_ALLOWED_ORIGINS",
    )
    # Brute-force protection: failed logins allowed per window before login is refused.
    login_max_failures_per_email: int = Field(
        default=5, ge=1, validation_alias="SIA_LOGIN_MAX_FAILURES_PER_EMAIL"
    )
    login_max_failures_per_ip: int = Field(
        default=20, ge=1, validation_alias="SIA_LOGIN_MAX_FAILURES_PER_IP"
    )
    login_failure_window_minutes: int = Field(
        default=15, ge=1, validation_alias="SIA_LOGIN_FAILURE_WINDOW_MINUTES"
    )

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure, has Path=/
        # and no Domain, so it cannot be set or overridden by another subdomain.
        return "__Host-sia_session" if self.is_production else "sia_session"

    @property
    def session_cookie_secure(self) -> bool:
        # Local development runs on plain http://, where browsers drop Secure cookies.
        return self.is_production

    @property
    def database_url(self) -> URL:
        """Runtime connection, as the restricted `sia_app` role (subject to Row-Level Security)."""
        return self._url(APP_DB_ROLE, self.app_db_password)

    @property
    def migration_database_url(self) -> URL:
        """Owner connection, for migrations and test setup only."""
        return self._url(self.postgres_user, self.postgres_password)

    def _url(self, username: str, password: SecretStr) -> URL:
        # URL.create escapes special characters in the password correctly.
        return URL.create(
            drivername="postgresql+asyncpg",
            username=username,
            password=password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()
