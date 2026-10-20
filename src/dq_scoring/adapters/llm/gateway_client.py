"""One-shot OpenAI-compatible chat-completions call to the operator-approved gateway.

No redirects, no proxy/env trust, no retries, no provider fallback, no tools. Errors carry only a fixed code.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from dq_scoring.adapters.llm.gateway_settings import LlmSettings

MAX_RESPONSE_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 64 * 1024

class AiError(Exception):
    """Safe, fixed-code failure of an advisory AI operation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GatewayReply:
    content: str
    model: str


async def complete_json(settings: LlmSettings, system: str, user: str) -> GatewayReply:
    """Send instructions (system) and context data (user) once; return the raw assistant text."""
    if not settings.configured:
        raise AiError("AI_NOT_CONFIGURED")
    body = json.dumps({
        "model": settings.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": settings.max_output_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
    }).encode()
    if len(body) > MAX_REQUEST_BYTES:
        raise AiError("AI_INVALID_OUTPUT")
    headers = {
        "Authorization": f"Bearer {settings.api_key.get_secret_value()}",  # type: ignore[union-attr]
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(settings.timeout_seconds)
    try:
        async with asyncio.timeout(settings.timeout_seconds), httpx.AsyncClient(
            verify=settings.ca_bundle or True, follow_redirects=False, trust_env=False, timeout=timeout,
        ) as client, client.stream("POST", settings.endpoint, content=body, headers=headers) as response:
            if response.status_code != 200:
                raise AiError("AI_UNAVAILABLE")
            raw = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=8192):
                if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise AiError("AI_INVALID_OUTPUT")
                raw += chunk
    except AiError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise AiError("AI_TIMEOUT") from None
    except (httpx.HTTPError, OSError, ValueError):
        raise AiError("AI_UNAVAILABLE") from None
    try:
        content = json.loads(raw)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AiError("AI_INVALID_OUTPUT") from None
    if not isinstance(content, str) or len(content) > MAX_RESPONSE_BYTES:
        raise AiError("AI_INVALID_OUTPUT")
    return GatewayReply(content=content, model=str(settings.model))


_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def require_enabled(settings: LlmSettings) -> None:
    if not settings.enabled:
        raise AiError("AI_DISABLED")
    if not settings.configured:
        raise AiError("AI_NOT_CONFIGURED")


@asynccontextmanager
async def gateway_slot(settings: LlmSettings) -> AsyncIterator[None]:
    """Bound in-flight gateway calls per process; excess requests fail fast instead of queueing."""
    semaphore = _SEMAPHORES.setdefault(settings.max_concurrency, asyncio.Semaphore(settings.max_concurrency))
    if semaphore.locked():
        raise AiError("AI_BUSY")
    async with semaphore:
        yield
