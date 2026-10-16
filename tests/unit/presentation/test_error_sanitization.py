"""Regression tests: API error responses never expose validation internals or SQL."""

from __future__ import annotations

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from dq_scoring.presentation.api.errors import register_exception_handlers


class _Strict(BaseModel):
    count: int


def _app() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/model")
    def model_error() -> None:
        _Strict(count="not-a-number")  # internal model construction bug

    @app.get("/unique")
    def unique() -> None:
        raise psycopg.errors.UniqueViolation('duplicate key value violates unique constraint "uq_data_assets_tenant_name"')

    @app.get("/check")
    def check() -> None:
        raise psycopg.errors.CheckViolation('new row for relation "quality_rules" violates check constraint "x"')

    return TestClient(app, raise_server_exceptions=False)


def test_internal_pydantic_errors_are_generic_500() -> None:
    resp = _app().get("/model")
    assert resp.status_code == 500
    assert "pydantic" not in resp.text and "_Strict" not in resp.text


@pytest.mark.parametrize(("path", "status"), [("/unique", 409), ("/check", 422)])
def test_constraint_violations_map_to_client_errors_without_sql(path: str, status: int) -> None:
    resp = _app().get(path)
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert "constraint" not in resp.text and "relation" not in resp.text
