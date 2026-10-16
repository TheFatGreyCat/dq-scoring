"""Unit tests for ApiSettings configuration and fail-fast validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dq_scoring.presentation.api.config import ApiSettings


@pytest.fixture(autouse=True)
def clean_dq_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ambient DQ_ environment variables to ensure clean test isolation."""
    for key in (
        "DQ_ENVIRONMENT",
        "DQ_APP_ENV",
        "DQ_JWT_SECRET",
        "DQ_AUTH_SECRET_KEY",
        "DQ_JWT_ALGORITHM",
        "DQ_AUTH_ALGORITHM",
        "DQ_ACCESS_TOKEN_EXPIRE_MINUTES",
        "DQ_AUTH_ACCESS_TOKEN_EXPIRE_MINUTES",
        "DQ_REFRESH_TOKEN_EXPIRE_DAYS",
        "DQ_AUTH_REFRESH_TOKEN_EXPIRE_DAYS",
        "DQ_POSTGRES_DSN",
        "DQ_TEST_POSTGRES_DSN",
        "DQ_CORS_ORIGINS",
        "DQ_LOGIN_MAX_FAILED_ATTEMPTS",
        "DQ_LOGIN_LOCKOUT_MINUTES",
    ):
        monkeypatch.delenv(key, raising=False)


DEV_SECRET = "development-only-secret-key-at-least-32-chars"
DEV_DSN = "postgresql://dq_app_user:synthetic@localhost:5432/dq_scoring"


def test_api_settings_defaults() -> None:
    """Verify non-secret defaults load cleanly once required secrets are supplied."""
    settings = ApiSettings(_env_file=None, environment="development", jwt_secret=DEV_SECRET, postgres_dsn=DEV_DSN)
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 30
    assert settings.refresh_token_expire_days == 14
    assert settings.environment == "development"


def test_api_settings_alias_support() -> None:
    """Verify alias support for DQ_AUTH_* and DQ_APP_ENV."""
    settings = ApiSettings(
        _env_file=None,
        postgres_dsn=DEV_DSN,
        app_env="development",
        auth_secret_key="custom-development-secret-key-32-chars-long",
        auth_algorithm="HS256",
        auth_access_token_expire_minutes=45,
        auth_refresh_token_expire_days=30,
    )
    assert settings.environment == "development"
    assert settings.jwt_secret == "custom-development-secret-key-32-chars-long"
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 45
    assert settings.refresh_token_expire_days == 30


def test_api_settings_production_fail_fast_on_insecure_secret() -> None:
    """Verify production rejects default/insecure JWT secret."""
    with pytest.raises(ValidationError, match="cryptographically secure"):
        ApiSettings(
            _env_file=None,
            environment="production",
            jwt_secret="dq-scoring-secret-key-minimum-32-chars-for-hmac-sha256",
            postgres_dsn=DEV_DSN,
        )


def test_api_settings_production_fail_fast_on_short_secret() -> None:
    """Verify production rejects short secret."""
    with pytest.raises(ValidationError, match="cryptographically secure"):
        ApiSettings(
            _env_file=None,
            environment="production",
            jwt_secret="too-short-secret",
            postgres_dsn=DEV_DSN,
        )


def test_api_settings_production_fail_fast_on_placeholder_dsn() -> None:
    """Verify production rejects placeholder postgres password."""
    with pytest.raises(ValidationError, match="without placeholder credentials"):
        ApiSettings(
            _env_file=None,
            environment="production",
            jwt_secret="a-valid-cryptographically-secure-secret-key-min-32-bytes",
            postgres_dsn="postgresql://dq_scoring:your_secure_postgres_password_here@localhost:5432/dq_scoring",
        )


def test_api_settings_production_valid() -> None:
    """Verify production loads successfully with valid credentials."""
    settings = ApiSettings(
        _env_file=None,
        environment="production",
        jwt_secret="a-valid-cryptographically-secure-secret-key-min-32-bytes",
        postgres_dsn="postgresql://dq_scoring:prod_strong_password_99281@db.prod.internal:5432/dq_scoring",
    )
    assert settings.environment == "production"
    assert settings.jwt_secret == "a-valid-cryptographically-secure-secret-key-min-32-bytes"


@pytest.mark.parametrize("missing", ["jwt_secret", "postgres_dsn"])
def test_api_settings_refuse_startup_without_required_secrets(missing: str) -> None:
    """Fail fast in every environment: no built-in JWT secret or credentialed DSN."""
    values = {"jwt_secret": DEV_SECRET, "postgres_dsn": DEV_DSN}
    values.pop(missing)
    with pytest.raises(ValidationError):
        ApiSettings(_env_file=None, environment="development", **values)


def test_api_settings_cors_defaults_to_no_cross_origin_access() -> None:
    settings = ApiSettings(_env_file=None, jwt_secret=DEV_SECRET, postgres_dsn=DEV_DSN)
    assert settings.cors_origins == []


def test_login_lockout_defaults_match_fr_auth_004() -> None:
    settings = ApiSettings(_env_file=None, jwt_secret=DEV_SECRET, postgres_dsn=DEV_DSN)
    assert (settings.login_max_failed_attempts, settings.login_lockout_minutes) == (5, 15)


def test_login_lockout_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQ_LOGIN_MAX_FAILED_ATTEMPTS", "3")
    monkeypatch.setenv("DQ_LOGIN_LOCKOUT_MINUTES", "30")
    settings = ApiSettings(_env_file=None, jwt_secret=DEV_SECRET, postgres_dsn=DEV_DSN)
    assert (settings.login_max_failed_attempts, settings.login_lockout_minutes) == (3, 30)


def test_runtime_dsn_ignores_test_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API must never silently switch to the destructive-test database."""
    from dq_scoring.presentation.api.dependencies import get_pg_dsn

    monkeypatch.delenv("DQ_RUNTIME_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("DQ_TEST_POSTGRES_DSN", "postgresql://u:p@localhost:5432/dq_scoring_test")
    settings = ApiSettings(_env_file=None, jwt_secret=DEV_SECRET, postgres_dsn=DEV_DSN)
    assert get_pg_dsn(settings) == DEV_DSN


@pytest.mark.parametrize("secret", ["change_this_to_a_cryptographically_secure_random_string_min_32_chars", "short"])
def test_placeholder_or_short_secrets_are_rejected_in_development_too(secret: str) -> None:
    """Copying .env.example verbatim must not yield a publicly known signing key."""
    with pytest.raises(ValidationError, match="cryptographically secure"):
        ApiSettings(_env_file=None, environment="development", jwt_secret=secret, postgres_dsn=DEV_DSN)
