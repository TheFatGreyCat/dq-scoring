"""Fixtures for E2E integration testing against PostgreSQL 16."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from dq_scoring.adapters.db.migrator import apply_all_migrations

DEFAULT_TEST_DSN = (
    "postgresql://dq_scoring:dq_scoring_test_pw@localhost:5432/dq_scoring_test"
)


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """Return PostgreSQL DSN from environment or dedicated test default."""
    test_dsn = os.getenv("DQ_TEST_POSTGRES_DSN") or DEFAULT_TEST_DSN
    primary_dsn = os.getenv("DQ_POSTGRES_DSN")
    if primary_dsn and test_dsn == primary_dsn:
        conn_info = psycopg.conninfo.conninfo_to_dict(test_dsn)
        dbname = conn_info.get("dbname", "")
        if "test" not in dbname.lower():
            raise RuntimeError(
                f"Refusing to run destructive tests against primary database '{dbname}'."
            )
    return test_dsn


@pytest.fixture(scope="session", autouse=True)
def db_migrated(pg_dsn: str) -> None:
    """Ensure database schema is up-to-date once per session."""
    with psycopg.connect(pg_dsn) as conn:
        apply_all_migrations(conn)


@pytest.fixture(autouse=True)
def clean_db(pg_dsn: str, db_migrated: None) -> Iterator[None]:
    """Clean database tables before and after each test for full isolation."""
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("TRUNCATE tenants, users CASCADE;")
        conn.commit()
    yield
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("TRUNCATE tenants, users CASCADE;")
        conn.commit()


@pytest.fixture
def db_conn(pg_dsn: str, db_migrated: None) -> Iterator[psycopg.Connection]:
    """Provide an isolated database connection for an E2E test."""
    conn = psycopg.connect(pg_dsn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def non_superuser_dsn(pg_dsn: str, db_migrated: None) -> str:
    """Ensure non-superuser runtime role exists and return DSN using it."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_app_user') THEN
                    CREATE ROLE dq_app_user WITH LOGIN PASSWORD 'dq_app_user_secret' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END $$;
            GRANT dq_app_role TO dq_app_user;
            GRANT USAGE ON SCHEMA public TO dq_app_user;
            """
        )
        conn.commit()

    conn_info = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    conn_info["user"] = "dq_app_user"
    conn_info["password"] = "dq_app_user_secret"
    return psycopg.conninfo.make_conninfo(**conn_info)


@pytest.fixture(autouse=True)
def setup_runtime_postgres_env(non_superuser_dsn: str) -> Iterator[None]:
    """Point API connections at the non-superuser runtime role for E2E tests."""
    previous = os.environ.get("DQ_RUNTIME_POSTGRES_DSN")
    os.environ["DQ_RUNTIME_POSTGRES_DSN"] = non_superuser_dsn
    yield
    if previous is not None:
        os.environ["DQ_RUNTIME_POSTGRES_DSN"] = previous
    else:
        os.environ.pop("DQ_RUNTIME_POSTGRES_DSN", None)
