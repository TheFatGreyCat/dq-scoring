"""Integration tests verifying database role privilege boundaries and RLS isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RunSpec
from dq_scoring.core.models import ScoringPolicy
from tests.support.run_seed import seed_run_prerequisites


def _seed_tenant(conn: psycopg.Connection, tenant_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING;
            """,
            (tenant_id, f"t-{tenant_id}", f"Tenant {tenant_id}"),
        )


def _make_spec(tenant_id: UUID) -> RunSpec:
    snap = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=tenant_id,
        asset_id=uuid4(),
        source_kind="OBJECT_FILE",
        source_descriptor={
            "bucket": "dq-snapshots-local",
            "key": f"snapshots/{tenant_id}/sample/raw.csv",
            "version_id": "v1",
            "content_sha256": "0" * 64,
            "size_bytes": 1024,
            "format": "CSV",
            "canonical": {
                "bucket": "dq-snapshots-local",
                "key": f"snapshots/{tenant_id}/sample/canonical.parquet",
                "version_id": "v1",
                "s3a_uri": f"s3a://dq-snapshots-local/snapshots/{tenant_id}/sample/canonical.parquet",
                "content_sha256": "0" * 64,
                "size_bytes": 1024,
                "format": "PARQUET",
            },
            "normalization_version": 1,
        },
        schema_definition={"columns": ["fare"]},
        total_rows=100,
        total_columns=1,
        captured_at=datetime.now(UTC),
    )
    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="R1_FARE_NON_NULL",
            dimension="completeness",
            rule_type="non_null",
            parameters={"column": "fare"},
            contribution_weight=1.0,
        )
    ]
    policy = ScoringPolicy(
        dimension_weights={"completeness": 1.0},
        publication_threshold=0.8,
        warn_min=60.0,
        pass_min=80.0,
    )
    return RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snap,
        rules=rules,
        policy=policy,
    )


def test_evaluation_runs_tenant_isolation_under_app_role(pg_dsn: str) -> None:
    """Verify dq_app_role cannot see other tenants' QUEUED or RUNNING evaluation runs."""
    tenant_a = uuid4()
    tenant_b = uuid4()

    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant(admin_conn, tenant_a)
        _seed_tenant(admin_conn, tenant_b)
        admin_conn.commit()

    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec_a = _make_spec(tenant_a)
    spec_a = seed_run_prerequisites(pg_dsn, spec_a)
    queue.enqueue_run(spec_a, idempotency_key=f"run-a-{uuid4()}")

    # 1. Tenant A under dq_app_role MUST see its own run
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction(), app_conn.cursor() as cur:
            set_tenant_context(app_conn, tenant_a)
            cur.execute("SELECT count(*) FROM evaluation_runs WHERE run_id = %s;", (spec_a.run_id,))
            assert cur.fetchone()[0] == 1

    # 2. Tenant B under dq_app_role MUST NOT see Tenant A's queued run
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction(), app_conn.cursor() as cur:
            set_tenant_context(app_conn, tenant_b)
            cur.execute("SELECT count(*) FROM evaluation_runs;")
            assert cur.fetchone()[0] == 0

    # 3. Fail-Closed: Querying under dq_app_role without context returns 0 runs
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction(), app_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM evaluation_runs;")
            assert cur.fetchone()[0] == 0

    # 4. Dispatcher Role without tenant context DOES see queued run for system claiming
    with psycopg.connect(pg_dsn) as disp_conn:
        disp_conn.execute("SET ROLE dq_dispatcher_role;")
        with disp_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM evaluation_runs WHERE run_status = 'QUEUED';")
            assert cur.fetchone()[0] >= 1


def test_dispatcher_role_claims_and_reclaims_via_adapter(pg_dsn: str) -> None:
    """Verify PostgresQueueAdapter runs end-to-end under dq_dispatcher_role."""
    tenant_id = uuid4()
    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant(admin_conn, tenant_id)
        admin_conn.commit()

    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = _make_spec(tenant_id)
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"run-disp-{uuid4()}")

    # Dispatcher claims the run using adapter connected as dq_dispatcher_role
    with psycopg.connect(pg_dsn) as disp_conn:
        disp_conn.execute("SET ROLE dq_dispatcher_role;")
        disp_queue = PostgresQueueAdapter(connection=disp_conn)

        leased = disp_queue.claim_next_run(worker_id="dispatcher-w1")
        assert leased is not None
        assert leased.run_id == spec.run_id
        assert leased.lease_generation == 1
        assert leased.spec.snapshot.total_rows == 100

    # Expire the lease
    with psycopg.connect(pg_dsn) as admin_conn, admin_conn.transaction():
        admin_conn.execute(
            "UPDATE evaluation_runs SET lease_expires_at = now() - interval '10 seconds' WHERE run_id = %s;",
            (spec.run_id,),
        )

    # Dispatcher reclaims the expired lease using adapter connected as dq_dispatcher_role
    with psycopg.connect(pg_dsn) as disp_conn:
        disp_conn.execute("SET ROLE dq_dispatcher_role;")
        disp_queue = PostgresQueueAdapter(connection=disp_conn)

        reclaimed = disp_queue.claim_next_run(worker_id="dispatcher-w2")
        assert reclaimed is not None
        assert reclaimed.run_id == spec.run_id
        assert reclaimed.lease_generation == 2


@pytest.mark.parametrize(
    "role", ["dq_app_role", "dq_worker_role", "dq_dispatcher_role", "dq_janitor_role", "dq_public_role"]
)
def test_service_roles_cannot_truncate_any_table(pg_dsn: str, role: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND has_table_privilege(%s, format('%%I.%%I', schemaname, tablename), 'TRUNCATE');",
            (role,),
        ).fetchall()
    assert rows == []
