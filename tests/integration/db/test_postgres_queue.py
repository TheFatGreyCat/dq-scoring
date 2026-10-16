"""Integration tests for PostgresQueueAdapter: concurrency, lease fencing, and timeouts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import (
    DatasetSnapshot,
    QualityRule,
    RunSpec,
    RunStatus,
    ScoringPolicy,
)
from tests.support.run_seed import seed_run_prerequisites


def _make_run_spec(tenant_id: UUID, priority: int = 5) -> RunSpec:
    """Helper to generate an independent RunSpec for queue testing."""
    snapshot = DatasetSnapshot(
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
            rule_code="R_NON_NULL",
            dimension="COMPLETENESS",
            rule_type="NON_NULL",
            parameters={"column": "fare"},
            contribution_weight=1.0,
        )
    ]
    policy = ScoringPolicy(
        dimension_weights={"COMPLETENESS": 1.0},
        publication_threshold=0.8,
        warn_min=60.0,
        pass_min=80.0,
    )
    return RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=rules,
        policy=policy,
        execution_profile="SPARK_K3S",
    )


def test_enqueue_run_does_not_create_missing_configuration(
    pg_dsn: str, test_tenant_id: UUID
) -> None:
    """enqueue_run must not seed users, snapshots, rulesets or policies it was not given."""
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name) VALUES (%s, %s, 'T');",
            (test_tenant_id, f"t-{test_tenant_id}"),
        )
    spec = _make_run_spec(test_tenant_id).model_copy(
        update={"ruleset_id": uuid4(), "policy_id": uuid4(), "created_by": uuid4()}
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(
            spec, idempotency_key=f"nocfg-{uuid4()}"
        )
    with psycopg.connect(pg_dsn) as conn:
        for table in ("users", "rulesets", "scoring_policies", "dataset_snapshots"):
            assert conn.execute(f"SELECT count(*) FROM {table};").fetchone()[0] == 0


def test_enqueue_run_idempotency(pg_dsn: str, test_tenant_id: UUID) -> None:
    """Verify enqueue_run is idempotent: re-enqueue with same key returns existing run_id."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = _make_run_spec(test_tenant_id)
    idemp_key = f"idemp-{uuid4()}"

    spec = seed_run_prerequisites(pg_dsn, spec)
    run_id_1 = queue.enqueue_run(spec, idempotency_key=idemp_key)
    assert run_id_1 == spec.run_id

    # Second enqueue with same tenant and idempotency key
    run_id_2 = queue.enqueue_run(spec, idempotency_key=idemp_key)
    assert run_id_2 == run_id_1

    # Verify only one row exists in evaluation_runs
    with psycopg.connect(pg_dsn) as conn:
        set_tenant_context(conn, test_tenant_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM evaluation_runs WHERE tenant_id = %s;",
                (test_tenant_id,),
            )
            assert cur.fetchone()[0] == 1


def test_claim_next_run_and_priority_ordering(
    pg_dsn: str, test_tenant_id: UUID
) -> None:
    """Verify runs are claimed in priority order (lower priority number = higher urgency)."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)

    spec_low = _make_run_spec(test_tenant_id)
    spec_high = _make_run_spec(test_tenant_id)

    spec_low = seed_run_prerequisites(pg_dsn, spec_low)
    queue.enqueue_run(spec_low, idempotency_key=f"low-{uuid4()}")
    spec_high = seed_run_prerequisites(pg_dsn, spec_high)
    queue.enqueue_run(spec_high, idempotency_key=f"high-{uuid4()}")

    # Update spec_high to priority 2, spec_low to priority 8
    with psycopg.connect(pg_dsn) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluation_runs SET priority = 8 WHERE run_id = %s;",
            (spec_low.run_id,),
        )
        cur.execute(
            "UPDATE evaluation_runs SET priority = 2 WHERE run_id = %s;",
            (spec_high.run_id,),
        )

    # First claim must pick spec_high (priority 2)
    claimed_1 = queue.claim_next_run(worker_id="worker-fast")
    assert claimed_1 is not None
    assert claimed_1.run_id == spec_high.run_id
    assert claimed_1.lease_generation == 1

    # Second claim must pick spec_low (priority 8)
    claimed_2 = queue.claim_next_run(worker_id="worker-slow")
    assert claimed_2 is not None
    assert claimed_2.run_id == spec_low.run_id
    assert claimed_2.lease_generation == 1

    # Third claim finds nothing
    claimed_3 = queue.claim_next_run(worker_id="worker-idle")
    assert claimed_3 is None


def test_concurrent_claims_skip_locked(pg_dsn: str, test_tenant_id: UUID) -> None:
    """Verify concurrent worker claims using FOR UPDATE SKIP LOCKED never collide."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    num_runs = 5
    specs = [_make_run_spec(test_tenant_id) for _ in range(num_runs)]
    for spec in specs:
        spec = seed_run_prerequisites(pg_dsn, spec)
        queue.enqueue_run(spec, idempotency_key=f"conc-{spec.run_id}")

    def _worker_claim(worker_idx: int):
        q = PostgresQueueAdapter(dsn=pg_dsn)
        return q.claim_next_run(worker_id=f"worker-{worker_idx}")

    with ThreadPoolExecutor(max_workers=num_runs) as executor:
        claimed_runs = list(executor.map(_worker_claim, range(num_runs)))

    # All 5 workers must successfully claim a distinct run
    assert all(r is not None for r in claimed_runs)
    claimed_ids = {r.run_id for r in claimed_runs if r is not None}
    assert len(claimed_ids) == num_runs
    expected_ids = {s.run_id for s in specs}
    assert claimed_ids == expected_ids


def test_heartbeat_lease_renewal_and_fencing(pg_dsn: str, test_tenant_id: UUID) -> None:
    """Verify heartbeat renews lease while valid and rejects stale lease generation."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = _make_run_spec(test_tenant_id)
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"hb-{uuid4()}")

    leased = queue.claim_next_run(worker_id="worker-hb")
    assert leased is not None
    assert leased.lease_generation == 1

    # Valid heartbeat with matching lease_generation
    renewed = queue.heartbeat(leased.run_id, leased.lease_generation)
    assert renewed is True

    # Stale heartbeat with outdated or mismatched generation
    stale_renew = queue.heartbeat(leased.run_id, lease_generation=999)
    assert stale_renew is False


def test_lease_timeout_expiration_and_reclaim(
    pg_dsn: str, test_tenant_id: UUID
) -> None:
    """Verify expired lease is re-claimable by another worker, and zombie worker is fenced."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = _make_run_spec(test_tenant_id)
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"timeout-{uuid4()}")

    # 1. Worker 1 claims run
    leased_1 = queue.claim_next_run(worker_id="worker-1")
    assert leased_1 is not None
    assert leased_1.lease_generation == 1

    # 2. Simulate lease expiration (lease_expires_at in past)
    with psycopg.connect(pg_dsn) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluation_runs SET lease_expires_at = now() - interval '5 seconds' WHERE run_id = %s;",
            (spec.run_id,),
        )

    # 3. Worker 2 claims expired run
    leased_2 = queue.claim_next_run(worker_id="worker-2")
    assert leased_2 is not None
    assert leased_2.run_id == spec.run_id
    assert leased_2.lease_generation == 2
    assert leased_2.worker_id == "worker-2"

    # 4. Zombie worker 1 attempts completion with stale generation 1 -> fenced
    fenced_res = queue.complete_run(
        run_id=spec.run_id,
        lease_generation=leased_1.lease_generation,
        status=RunStatus.SUCCEEDED,
    )
    assert fenced_res is False
    assert queue.get_run_status(spec.run_id) == RunStatus.LEASED

    # 5. Worker 2 with active generation 2 successfully completes run
    completed_res = queue.complete_run(
        run_id=spec.run_id,
        lease_generation=leased_2.lease_generation,
        status=RunStatus.SUCCEEDED,
    )
    assert completed_res is True
    assert queue.get_run_status(spec.run_id) == RunStatus.SUCCEEDED


def test_lease_expired_without_reclaim_rejects_heartbeat_and_completion(
    pg_dsn: str, test_tenant_id: UUID
) -> None:
    """Verify that an expired lease cannot be extended via heartbeat or completed, even if unreclaimed."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = _make_run_spec(test_tenant_id)
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"ttl-expire-{uuid4()}")

    leased = queue.claim_next_run(worker_id="worker-slow")
    assert leased is not None
    assert leased.lease_generation == 1

    # Simulate lease expiration in the past
    with psycopg.connect(pg_dsn) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluation_runs SET lease_expires_at = now() - interval '10 seconds' WHERE run_id = %s;",
            (spec.run_id,),
        )

    # 1. Heartbeat must be rejected
    hb_success = queue.heartbeat(spec.run_id, leased.lease_generation)
    assert hb_success is False

    # 2. Complete run must be rejected
    comp_success = queue.complete_run(
        spec.run_id,
        leased.lease_generation,
        status=RunStatus.SUCCEEDED,
    )
    assert comp_success is False

    # Run remains in LEASED status until reclaimed
    assert queue.get_run_status(spec.run_id) == RunStatus.LEASED


def test_dispatcher_role_reclaim_expired_lease(
    pg_dsn: str, test_tenant_id: UUID
) -> None:
    """Verify that dq_dispatcher_role RLS policy allows selecting and reclaiming expired runs cross-tenant."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = _make_run_spec(test_tenant_id)
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"disp-reclaim-{uuid4()}")

    leased = queue.claim_next_run(worker_id="worker-first")
    assert leased is not None
    assert leased.lease_generation == 1

    # Expire lease
    with psycopg.connect(pg_dsn) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluation_runs SET lease_expires_at = now() - interval '15 seconds' WHERE run_id = %s;",
            (spec.run_id,),
        )

    # Use dq_dispatcher_role without setting tenant context
    with psycopg.connect(pg_dsn) as disp_conn:
        disp_conn.execute("SET ROLE dq_dispatcher_role;")

        # Dispatcher RLS SELECT policy must find expired run
        with disp_conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, lease_generation FROM evaluation_runs
                WHERE run_id = %s
                  AND (run_status = 'QUEUED' OR (run_status IN ('LEASED', 'RUNNING') AND lease_expires_at < now()));
                """,
                (spec.run_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == spec.run_id
            assert row[1] == 1

        # Dispatcher RLS UPDATE policy must allow reclaiming lease
        with disp_conn.transaction(), disp_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE evaluation_runs
                SET run_status = 'LEASED',
                    lease_owner = 'dispatcher-worker-2',
                    lease_generation = lease_generation + 1,
                    lease_expires_at = now() + interval '300 seconds'
                WHERE run_id = %s;
                """,
                (spec.run_id,),
            )
            assert cur.rowcount == 1
