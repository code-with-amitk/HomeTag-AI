"""
> Why: Load and validate environment-based application configuration.
> Throughput: Read once at process startup; settings are cached for later access.
> Dependencies: Pydantic Settings and the local .env file for development.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HOMETAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="HomeTag AI", description="Name exposed by the API.")
    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        description="Deployment environment name.",
    )
    database_url: str = Field(
        default="postgresql+psycopg://hometag:hometag_dev_only@localhost:5432/hometag",
        description="PostgreSQL SQLAlchemy connection URL.",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL used by readiness checks and Celery.",
    )
    jwt_secret_key: str = Field(
        default="local-development-only-secret-change-before-deploy",
        min_length=32,
        description="Secret used to sign access tokens; set a unique secret outside development.",
    )
    access_token_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
        description="Lifetime of a bearer access token in minutes.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Minimum application log level.",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Require PostgreSQL and normalize its default SQLAlchemy driver."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use PostgreSQL with the psycopg driver")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        """Require a Redis connection URL."""
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use redis:// or rediss://")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def reject_development_secret_in_production(cls, value: str, info: ValidationInfo) -> str:
        """Prevent the development fallback from being used in production."""
        if (
            info.data.get("environment") == "production"
            and value == "local-development-only-secret-change-before-deploy"
        ):
            raise ValueError("jwt_secret_key must be configured in production")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
