"""Typed S3 / MinIO storage and import processing configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class S3Settings(BaseSettings):
    """S3 object store connection settings loaded from environment (DQ_S3_)."""

    model_config = SettingsConfigDict(
        env_prefix="DQ_S3_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    endpoint_url: str
    access_key_id: SecretStr
    secret_access_key: SecretStr
    region: str = Field(default="us-east-1")
    use_ssl: bool = Field(default=False)
    ca_bundle: str | None = Field(default=None)
    bucket_staging: str = Field(default="dq-staging-local")
    bucket_snapshots: str = Field(default="dq-snapshots-local")
    bucket_artifacts: str = Field(default="dq-artifacts-local")

    @model_validator(mode="after")
    def _validate_endpoint(self) -> Self:
        parsed = urlparse(self.endpoint_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid S3 endpoint URL scheme '{parsed.scheme}'; must be http or https")
        env = os.getenv("DQ_APP_ENV", "development").lower()
        protected = os.getenv("DQ_PROTECTED_PROCESSING_ENABLED", "").strip().lower() in ("true", "1", "yes")
        if protected or env in ("production", "staging"):
            if parsed.scheme != "https":
                raise ValueError(f"HTTPS required for S3 endpoint in {env} environment, got: {self.endpoint_url}")
            raw_key = self.access_key_id.get_secret_value()
            raw_sec = self.secret_access_key.get_secret_value()
            if not raw_key or raw_key == "minioadmin":
                raise ValueError(f"Real non-default access_key_id is required in {env} environment")
            if not raw_sec or raw_sec == "minioadmin":
                raise ValueError(f"Real non-default secret_access_key is required in {env} environment")
        if protected:
            if not self.use_ssl:
                raise ValueError("use_ssl must be true when protected processing is enabled")
            bundle = self.ca_bundle or os.getenv("DQ_S3_CA_BUNDLE")
            if not bundle or not os.path.isfile(bundle):
                raise ValueError("CA bundle file required and must exist when protected processing is enabled")
        return self


class ImportSettings(BaseSettings):
    """Limits and processing parameters for dataset ingestion."""

    model_config = SettingsConfigDict(
        env_prefix="DQ_IMPORT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_bytes: int = Field(default=21474836480, ge=1)  # 20 GiB
    part_bytes: int = Field(default=16777216, ge=5242880)  # 16 MiB (min 5 MiB for S3 parts)
    max_columns: int = Field(default=1000, ge=1)
    max_record_bytes: int = Field(default=8388608, ge=1024)  # 8 MiB
    temp_root: str = Field(default=".tmp/imports")
    lease_seconds: int = Field(default=60, ge=10)
    heartbeat_seconds: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _validate_timing(self) -> Self:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError(
                f"heartbeat_seconds ({self.heartbeat_seconds}) must be strictly less than lease_seconds ({self.lease_seconds})"
            )
        return self


@lru_cache(maxsize=1)
def get_s3_settings() -> S3Settings:
    """Return cached S3 settings singleton."""
    return S3Settings()


@lru_cache(maxsize=1)
def get_import_settings() -> ImportSettings:
    """Return cached import settings singleton."""
    return ImportSettings()
