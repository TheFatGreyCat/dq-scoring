"""Unit tests for S3Settings and S3 configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic.types import SecretStr

from dq_scoring.adapters.storage.s3_settings import (
    S3Settings,
)


def test_s3_settings_rejects_non_http_schemes() -> None:
    with pytest.raises(ValidationError, match="scheme"):
        S3Settings(
            endpoint_url="ftp://localhost:9000",
            access_key_id=SecretStr("minioadmin"),
            secret_access_key=SecretStr("minioadmin_secret"),
        )


def test_s3_settings_requires_https_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQ_APP_ENV", "production")
    with pytest.raises(ValidationError, match="HTTPS required"):
        S3Settings(
            endpoint_url="http://storage.internal:9000",
            access_key_id=SecretStr("key"),
            secret_access_key=SecretStr("secret"),
        )

    # HTTPS is accepted in production
    valid = S3Settings(
        endpoint_url="https://storage.internal:9000",
        access_key_id=SecretStr("key"),
        secret_access_key=SecretStr("secret"),
    )
    assert valid.endpoint_url == "https://storage.internal:9000"


def test_s3_settings_enforces_protected_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")

    # HTTP rejected in protected mode even in development env
    monkeypatch.setenv("DQ_APP_ENV", "development")
    with pytest.raises(ValidationError, match="HTTPS required"):
        S3Settings(
            endpoint_url="http://storage.internal:9000",
            access_key_id=SecretStr("key"),
            secret_access_key=SecretStr("secret"),
            use_ssl=True,
        )

    # use_ssl=False rejected in protected mode
    with pytest.raises(ValidationError, match="use_ssl"):
        S3Settings(
            endpoint_url="https://storage.internal:9000",
            access_key_id=SecretStr("key"),
            secret_access_key=SecretStr("secret"),
            use_ssl=False,
        )

    # Missing CA bundle rejected in protected mode
    with pytest.raises(ValidationError, match="CA bundle"):
        S3Settings(
            endpoint_url="https://storage.internal:9000",
            access_key_id=SecretStr("key"),
            secret_access_key=SecretStr("secret"),
            use_ssl=True,
            ca_bundle="/nonexistent/ca.pem",
        )

    # Valid with existing CA bundle
    ca_file = tmp_path / "s3-ca.pem"
    ca_file.write_text("ca")
    valid = S3Settings(
        endpoint_url="https://storage.internal:9000",
        access_key_id=SecretStr("key"),
        secret_access_key=SecretStr("secret"),
        use_ssl=True,
        ca_bundle=str(ca_file),
    )
    assert valid.ca_bundle == str(ca_file)




