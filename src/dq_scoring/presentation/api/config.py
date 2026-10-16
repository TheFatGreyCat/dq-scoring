"""Configuration settings for FastAPI API application using pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_CHARS = 32
"""HMAC-SHA256 signing key length floor (characters)."""

INSECURE_DEFAULT_SECRETS: frozenset[str] = frozenset({
    "dq-scoring-secret-key-minimum-32-chars-for-hmac-sha256",
    "change_this_to_a_cryptographically_secure_random_string_min_32_chars",
    "secret",
    "password",
})


class ApiSettings(BaseSettings):
    """Fail-fast application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="DQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_dsn: str = Field(
        validation_alias=AliasChoices("postgres_dsn", "DQ_POSTGRES_DSN"),
        description="Primary PostgreSQL connection string",
    )
    test_postgres_dsn: str | None = Field(
        default=None,
        validation_alias=AliasChoices("test_postgres_dsn", "DQ_TEST_POSTGRES_DSN"),
        description="Dedicated test PostgreSQL DSN",
    )
    jwt_secret: str = Field(
        validation_alias=AliasChoices(
            "jwt_secret",
            "auth_secret_key",
            "DQ_JWT_SECRET",
            "DQ_AUTH_SECRET_KEY",
        ),
        description="HMAC secret key for JWT signing",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices(
            "jwt_algorithm",
            "auth_algorithm",
            "DQ_JWT_ALGORITHM",
            "DQ_AUTH_ALGORITHM",
        ),
        description="Algorithm for JWT encoding",
    )
    access_token_expire_minutes: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "access_token_expire_minutes",
            "auth_access_token_expire_minutes",
            "DQ_ACCESS_TOKEN_EXPIRE_MINUTES",
            "DQ_AUTH_ACCESS_TOKEN_EXPIRE_MINUTES",
        ),
        description="Access token TTL in minutes",
    )
    refresh_token_expire_days: int = Field(
        default=14,
        validation_alias=AliasChoices(
            "refresh_token_expire_days",
            "auth_refresh_token_expire_days",
            "DQ_REFRESH_TOKEN_EXPIRE_DAYS",
            "DQ_AUTH_REFRESH_TOKEN_EXPIRE_DAYS",
        ),
        description="Refresh token TTL in days",
    )
    login_max_failed_attempts: int = Field(
        default=5,
        ge=1,
        validation_alias=AliasChoices("login_max_failed_attempts", "DQ_LOGIN_MAX_FAILED_ATTEMPTS"),
        description="Consecutive failed logins that lock the account (FR-AUTH-004)",
    )
    login_lockout_minutes: int = Field(
        default=15,
        ge=1,
        validation_alias=AliasChoices("login_lockout_minutes", "DQ_LOGIN_LOCKOUT_MINUTES"),
        description="Account lockout duration in minutes (FR-AUTH-004)",
    )
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices(
            "environment",
            "app_env",
            "DQ_ENVIRONMENT",
            "DQ_APP_ENV",
        ),
        description="Runtime environment name",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("cors_origins", "DQ_CORS_ORIGINS"),
        description="Allowed CORS origin domains",
    )

    @model_validator(mode="after")
    def validate_security_invariants(self) -> ApiSettings:
        """Enforce fail-fast security invariants (signing key in every environment)."""
        if self.jwt_secret in INSECURE_DEFAULT_SECRETS or len(self.jwt_secret) < MIN_JWT_SECRET_CHARS:
            raise ValueError(
                "A cryptographically secure DQ_AUTH_SECRET_KEY / DQ_JWT_SECRET of at least "
                f"{MIN_JWT_SECRET_CHARS} characters is required (placeholder values are rejected)."
            )
        if (
            self.environment.lower() in ("production", "staging", "prod")
            and "your_secure_postgres_password_here" in self.postgres_dsn
        ):
            raise ValueError(
                "Production/staging environment requires a valid DQ_POSTGRES_DSN "
                "without placeholder credentials."
            )
        return self


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Load settings once per process (validated at first use, not re-read per request)."""
    return ApiSettings()
