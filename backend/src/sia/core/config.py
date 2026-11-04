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
    postgres_user: str = Field(validation_alias="POSTGRES_USER")
    # SecretStr keeps the password out of logs, tracebacks and `repr()` output.
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="sia_dev", validation_alias="POSTGRES_DB")
    db_pool_size: int = Field(default=5, ge=1, validation_alias="SIA_DB_POOL_SIZE")
    db_connect_timeout_seconds: float = Field(
        default=5.0, gt=0, validation_alias="SIA_DB_CONNECT_TIMEOUT_SECONDS"
    )

    @property
    def database_url(self) -> URL:
        """SQLAlchemy URL for the async driver. Built with `URL.create` so special characters
        in the password are escaped correctly."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
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
