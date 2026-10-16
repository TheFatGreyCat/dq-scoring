"""Fixtures for database integration testing against PostgreSQL 16."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dq_scoring.adapters.db.migrator import apply_all_migrations
from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RunSpec
from dq_scoring.core.models import ScoringPolicy
from dq_scoring.presentation.api.app import create_app
from dq_scoring.presentation.api.auth import hash_password
from dq_scoring.presentation.api.dependencies import get_pg_dsn

DEFAULT_TEST_DSN = (
    "postgresql://dq_scoring:dq_scoring_test@localhost:5432/dq_scoring_test"
)
PASSWORD = "Synthetic-Password-123!"


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
    """Set DQ_RUNTIME_POSTGRES_DSN so API endpoints use non-superuser runtime role by default."""
    previous = os.environ.get("DQ_RUNTIME_POSTGRES_DSN")
    os.environ["DQ_RUNTIME_POSTGRES_DSN"] = non_superuser_dsn
    yield
    if previous is not None:
        os.environ["DQ_RUNTIME_POSTGRES_DSN"] = previous
    else:
        os.environ.pop("DQ_RUNTIME_POSTGRES_DSN", None)


@pytest.fixture
def client(non_superuser_dsn: str) -> TestClient:
    """FastAPI TestClient fixture running under non-superuser runtime role."""
    app = create_app()
    app.dependency_overrides[get_pg_dsn] = lambda: non_superuser_dsn
    return TestClient(app)

@pytest.fixture
def db_conn(pg_dsn: str, db_migrated: None) -> Iterator[psycopg.Connection]:
    """Provide an isolated database connection for an integration test."""
    conn = psycopg.connect(pg_dsn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def test_tenant_id() -> UUID:
    """Generate a unique tenant ID for test isolation."""
    return uuid4()


@pytest.fixture
def sample_snapshot(test_tenant_id: UUID) -> DatasetSnapshot:
    """Generate a sample snapshot entity."""
    asset_id = uuid4()
    return DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=test_tenant_id,
        asset_id=asset_id,
        source_kind="OBJECT_FILE",
        source_descriptor={
            "bucket": "dq-snapshots-local",
            "key": f"snapshots/{test_tenant_id}/sample/raw.csv",
            "version_id": "v1",
            "content_sha256": "0" * 64,
            "size_bytes": 1024,
            "format": "CSV",
            "canonical": {
                "bucket": "dq-snapshots-local",
                "key": f"snapshots/{test_tenant_id}/sample/canonical.parquet",
                "version_id": "v1",
                "s3a_uri": f"s3a://dq-snapshots-local/snapshots/{test_tenant_id}/sample/canonical.parquet",
                "content_sha256": "0" * 64,
                "size_bytes": 1024,
                "format": "PARQUET",
            },
            "normalization_version": 1,
        },
        schema_definition={"columns": ["trip_seconds", "fare"]},
        total_rows=100,
        total_columns=2,
        captured_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_run_spec(test_tenant_id: UUID, sample_snapshot: DatasetSnapshot) -> RunSpec:
    """Generate a sample execution specification."""
    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="R1_NON_NULL",
            dimension="completeness",
            rule_type="non_null",
            parameters={"column": "fare"},
            contribution_weight=1.0,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="R2_POSITIVE",
            dimension="validity",
            rule_type="domain_range",
            parameters={"column": "fare", "min": 0},
            contribution_weight=1.0,
        ),
    ]
    policy = ScoringPolicy(
        dimension_weights={"completeness": 0.5, "validity": 0.5},
        publication_threshold=0.80,
        warn_min=60.0,
        pass_min=80.0,
    )
    return RunSpec(
        run_id=uuid4(),
        tenant_id=test_tenant_id,
        snapshot=sample_snapshot,
        rules=rules,
        policy=policy,
    )

def _login(client: TestClient, email: str, tenant_id: UUID) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD, "tenant_id": str(tenant_id)})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@dataclass(frozen=True)
class Tenant:
    tenant_id: UUID
    creator: dict[str, str]
    approver: dict[str, str]


@pytest.fixture
def tenant(client: TestClient, db_conn: psycopg.Connection) -> Tenant:
    """One tenant with a DATA_ENGINEER creator and a DATA_STEWARD approver."""
    tenant_id, creator_id, approver_id = uuid4(), uuid4(), uuid4()
    pwd_hash = hash_password(PASSWORD)
    emails = {
        creator_id: f"creator_{creator_id.hex[:8]}@example.com",
        approver_id: f"approver_{approver_id.hex[:8]}@example.com",
    }
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s, %s, 'Audit Org', 'ENTERPRISE', 'ACTIVE');",
            (tenant_id, f"audit_{tenant_id.hex[:8]}"),
        )
        for uid, email in emails.items():
            cur.execute(
                "INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, %s, 'Synthetic User', TRUE);",
                (uid, email, pwd_hash),
            )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE'), (%s, %s, 'DATA_STEWARD', 'ACTIVE');",
            (tenant_id, creator_id, tenant_id, approver_id),
        )
        db_conn.commit()
    return Tenant(
        tenant_id=tenant_id,
        creator=_login(client, emails[creator_id], tenant_id),
        approver=_login(client, emails[approver_id], tenant_id),
    )
