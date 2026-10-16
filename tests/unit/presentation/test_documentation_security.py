"""Documentation scripts must work without relaxing API response policies."""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.middleware import SecurityHeadersMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("path", ["/docs", "/docs/oauth2-redirect", "/redoc"])
def test_documentation_allows_its_scripts_without_arbitrary_inline_code(client, path):
    response = client.get(path)
    assert response.status_code == 200
    directives = {
        tokens[0]: tokens[1:]
        for directive in response.headers["content-security-policy"].split(";")
        if (tokens := directive.split())
    }
    sources = directives.get("script-src", directives["default-src"])
    for attributes, script in re.findall(r"<script\b([^>]*)>(.*?)</script>", response.text, re.DOTALL):
        src = re.search(r'src="([^"]+)"', attributes)
        if src:
            assert any(src[1].startswith(source) for source in sources if source.startswith("https://"))
        elif script.strip():
            digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
            assert f"'sha256-{digest}'" in sources
    assert "'unsafe-inline'" not in sources
    assert "*" not in sources


def test_non_documentation_keeps_strict_policy(client):
    response = client.get("/health")
    assert response.headers["content-security-policy"] == "default-src 'self'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
