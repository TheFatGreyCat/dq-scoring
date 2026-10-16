"""Security and HTTP Header sanitization middlewares conforming to AC-025."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from typing import Any

from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_NO_STORE_PREFIXES = ("/api/v1/imports", "/api/v1/storage", "/api/v1/snapshots", "/api/v1/sensitive-findings", "/api/v1/privacy")
_NO_STORE_SUFFIXES = ("/column-classifications", "/protection-policy", "/masked-export")


def _is_no_store_path(path: str) -> bool:
    return path.startswith(_NO_STORE_PREFIXES) or path.endswith(_NO_STORE_SUFFIXES)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing secure response headers and stripping server fingerprint headers."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)

        # 1. Strip server fingerprint headers (AC-025)
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]

        # 2. Inject standard security protective headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        if request.url.path in {"/docs", "/docs/oauth2-redirect", "/redoc"} and response.headers.get("content-type", "").startswith("text/html"):
            body = b"".join([chunk async for chunk in response.body_iterator])
            response.body_iterator = iterate_in_threadpool(iter([body]))
            script_hashes = " ".join(
                "'sha256-" + base64.b64encode(hashlib.sha256(script).digest()).decode() + "'"
                for attributes, script in re.findall(rb"<script\b([^>]*)>(.*?)</script>", body, re.DOTALL)
                if b"src=" not in attributes and script.strip()
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' https://cdn.jsdelivr.net/npm/ {script_hashes}; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net/npm/ https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
            )
        if _is_no_store_path(request.url.path):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"

        return response
