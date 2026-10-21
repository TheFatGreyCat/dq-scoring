"""Operator-owned configuration for the deployment's read-only shared S3 source."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dq_scoring.adapters.storage.s3_settings import S3Settings
from dq_scoring.common.hash_utils import compute_deterministic_hash


def normalized_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid source endpoint')
    port = parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)
    host = parsed.hostname.lower()
    if ':' in host:
        host = f'[{host}]'
    return f'{parsed.scheme.lower()}://{host}:{port}{parsed.path.rstrip("/")}'


class SourceStoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='DQ_SOURCE_S3_', extra='ignore', env_file=None, env_ignore_empty=True)

    enabled: bool = False
    endpoint_url: str | None = None
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    region: str = 'us-east-1'
    use_ssl: bool = False
    ca_bundle: str | None = None
    ca_secret: str | None = None
    bucket: str | None = None
    tenant_prefixes: dict[UUID, list[str]] = Field(default_factory=dict)
    retention_guaranteed: bool = False
    executor_secret: str | None = None
    access_key_id_key: str = 'access_key'
    secret_access_key_key: str = 'secret_key'

    @model_validator(mode='after')
    def validate_source(self) -> Self:
        if self.endpoint_url:
            normalized_endpoint(self.endpoint_url)
        if not self.enabled:
            return self
        if not self.endpoint_url or not self.bucket or not self.access_key_id or not self.secret_access_key or not self.tenant_prefixes:
            raise ValueError('Enabled source requires endpoint, bucket, credentials and tenant prefixes')
        if not self.access_key_id.get_secret_value() or not self.secret_access_key.get_secret_value():
            raise ValueError('Source credentials must be nonempty')
        prefixes: list[tuple[UUID, str]] = []
        for tenant, values in self.tenant_prefixes.items():
            if not values:
                raise ValueError('Source tenant prefixes must be nonempty')
            for prefix in values:
                if not prefix or not prefix.endswith('/') or prefix.startswith('/') or '\\' in prefix or any(ord(c) < 32 or ord(c) == 127 for c in prefix) or any(p in ('', '.', '..') for p in prefix[:-1].split('/')):
                    raise ValueError('Invalid source tenant prefix')
                for other, existing in prefixes:
                    if other != tenant and (prefix.startswith(existing) or existing.startswith(prefix)):
                        raise ValueError('Source tenant prefixes overlap')
                prefixes.append((tenant, prefix))
        protected = os.getenv('DQ_PROTECTED_PROCESSING_ENABLED', '').strip().lower() in ('true', '1', 'yes')
        if protected and (not self.ca_bundle or not os.path.isfile(self.ca_bundle)):
            raise ValueError('Dedicated source CA bundle file is required in protected mode')
        self.as_s3_settings()
        return self

    def as_s3_settings(self) -> S3Settings:
        if not self.endpoint_url or not self.bucket or not self.access_key_id or not self.secret_access_key:
            raise ValueError('Source connection is not configured')
        return S3Settings(_env_file=None, endpoint_url=self.endpoint_url, access_key_id=self.access_key_id,
                          secret_access_key=self.secret_access_key, region=self.region, use_ssl=self.use_ssl,
                          ca_bundle=self.ca_bundle, bucket_staging=self.bucket, bucket_snapshots=self.bucket,
                          bucket_artifacts=self.bucket)

    def validate_owned_separation(self, owned: S3Settings) -> None:
        if self.enabled and normalized_endpoint(self.endpoint_url or '') == normalized_endpoint(owned.endpoint_url) and self.bucket in (owned.bucket_staging, owned.bucket_snapshots, owned.bucket_artifacts):
            raise ValueError('External source must not share an owned bucket')


def source_binding_sha256(settings: SourceStoreSettings) -> str:
    return compute_deterministic_hash({'endpoint_url': normalized_endpoint(settings.endpoint_url or ''), 'bucket': settings.bucket})


@lru_cache(maxsize=1)
def get_source_settings() -> SourceStoreSettings:
    return SourceStoreSettings()
