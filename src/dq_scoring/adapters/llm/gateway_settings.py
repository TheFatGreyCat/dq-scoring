"""Operator-owned LLM gateway configuration. Disabled unless explicitly enabled."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DQ_LLM_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    enabled: bool = False
    endpoint: str | None = Field(default=None, max_length=512, description="HTTPS chat-completions URL")
    model: str | None = Field(default=None, max_length=128)
    api_key: SecretStr | None = None
    ca_bundle: str | None = Field(default=None, description="Optional PEM CA bundle path for the gateway")
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_output_tokens: int = Field(default=1024, ge=64, le=4096)
    max_columns: int = Field(default=50, ge=1, le=200)
    max_concurrency: int = Field(default=2, ge=1, le=16)

    @property
    def configured(self) -> bool:
        url = urlsplit(self.endpoint or "")
        return bool(
            url.scheme == "https" and url.hostname and not url.username and not url.password and not url.fragment
            and self.model and self.api_key and self.api_key.get_secret_value()
        )


@lru_cache(maxsize=1)
def get_llm_settings() -> LlmSettings:
    return LlmSettings()
