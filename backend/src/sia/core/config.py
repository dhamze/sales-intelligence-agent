"""Application configuration, loaded from environment variables (and `.env` in development).

All settings are validated at startup: a missing or malformed value stops the app immediately
with a clear error, instead of failing later in some unrelated code path.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["console", "json"]
LLMProvider = Literal["anthropic", "fake"]
FetchProvider = Literal["web", "fake"]
Effort = Literal["low", "medium", "high"]
MIN_PRODUCTION_PASSWORD = 24

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

    # --- Enrichment (website reading + AI extraction) ---
    # The Anthropic SDK's standard variable name; read from .env like every other setting.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    llm_provider: LLMProvider = Field(default="anthropic", validation_alias="SIA_LLM_PROVIDER")
    fetch_provider: FetchProvider = Field(default="web", validation_alias="SIA_FETCH_PROVIDER")
    enrichment_model: str = Field(
        default="claude-opus-5-5", validation_alias="SIA_ENRICHMENT_MODEL"
    )
    enrichment_effort: Effort = Field(default="low", validation_alias="SIA_ENRICHMENT_EFFORT")
    enrichment_daily_limit: int = Field(
        default=200, ge=0, validation_alias="SIA_ENRICHMENT_DAILY_LIMIT"
    )

    # --- AI account briefs (same provider and API key as enrichment) ---
    brief_model: str = Field(default="claude-opus-5-5", validation_alias="SIA_BRIEF_MODEL")
    brief_effort: Effort = Field(default="medium", validation_alias="SIA_BRIEF_EFFORT")
    brief_daily_limit: int = Field(default=50, ge=0, validation_alias="SIA_BRIEF_DAILY_LIMIT")

    # --- Error monitoring (Sentry; off unless a DSN is set) ---
    sentry_dsn: SecretStr | None = Field(default=None, validation_alias="SENTRY_DSN")
    # Share of requests traced for performance (0 = errors only, which fits the free tier).
    sentry_traces_sample_rate: float = Field(
        default=0.0, ge=0, le=1, validation_alias="SIA_SENTRY_TRACES_SAMPLE_RATE"
    )
    # Version identifier shown in Sentry (the deploy sets it to the git commit).
    release: str | None = Field(default=None, validation_alias="SIA_RELEASE")

    # --- Cost and abuse protection ---
    # Estimated AI spend allowed per calendar month (UTC) across ALL organisations; AI features
    # pause when it is reached. None = no limit (development).
    ai_monthly_budget_usd: Decimal | None = Field(
        default=None, ge=0, validation_alias="SIA_AI_MONTHLY_BUDGET_USD"
    )
    # Whether organisations created by signup may use AI. The public demo sets this to false.
    ai_enabled_for_new_orgs: bool = Field(
        default=True, validation_alias="SIA_AI_ENABLED_FOR_NEW_ORGS"
    )
    rate_limit_enabled: bool = Field(default=True, validation_alias="SIA_RATE_LIMIT_ENABLED")
    # Per client IP. Generous for normal use (the UI polls every 2 s while jobs run).
    rate_limit_requests_per_minute: int = Field(
        default=600, ge=1, validation_alias="SIA_RATE_LIMIT_REQUESTS_PER_MINUTE"
    )
    rate_limit_writes_per_minute: int = Field(
        default=60, ge=1, validation_alias="SIA_RATE_LIMIT_WRITES_PER_MINUTE"
    )
    rate_limit_signups_per_hour: int = Field(
        default=5, ge=1, validation_alias="SIA_RATE_LIMIT_SIGNUPS_PER_HOUR"
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

    @model_validator(mode="after")
    def _no_fakes_in_production(self) -> Self:
        """Fake AI/fetch providers exist for tests and demos; never let them run in production."""
        if self.is_production and "fake" in (self.llm_provider, self.fetch_provider):
            raise ValueError("Fake enrichment providers cannot be used in production.")
        return self

    @model_validator(mode="after")
    def _safe_production_config(self) -> Self:
        """Refuse to start in production with settings that are only acceptable locally."""
        if not self.is_production:
            return self
        if not self.allowed_origins or any(
            not origin.startswith("https://") for origin in self.allowed_origins
        ):
            raise ValueError("In production, SIA_ALLOWED_ORIGINS must list https:// origins only.")
        for name, secret in (
            ("POSTGRES_PASSWORD", self.postgres_password),
            ("SIA_APP_DB_PASSWORD", self.app_db_password),
        ):
            value = secret.get_secret_value()
            if len(value) < MIN_PRODUCTION_PASSWORD or "change-me" in value:
                raise ValueError(
                    f"In production, {name} must be a random value of at least "
                    f"{MIN_PRODUCTION_PASSWORD} characters."
                )
        return self

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
