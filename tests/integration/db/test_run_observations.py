"""Run-scoped Spark observations are lease fenced and append-only (run_events)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from tests.integration.db.test_postgres_queue import _make_run_spec
from tests.support.run_seed import seed_run_prerequisites

OBSERVATION = {"application_id": "app-1", "group_id": "g", "jobs": []}


@pytest.fixture
def leased(pg_dsn, test_tenant_id):
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = seed_run_prerequisites(pg_dsn, _make_run_spec(test_tenant_id))
    queue.enqueue_run(spec, idempotency_key=f"obs-{uuid4()}")
    return queue, queue.claim_next_run(worker_id="w1"), spec


def observed(pg_dsn, run_id):
    with psycopg.connect(pg_dsn) as conn:
        return conn.execute(
            "SELECT lease_generation FROM run_events WHERE run_id=%s AND event_type='SPARK_OBSERVED' ORDER BY created_at;",
            (run_id,),
        ).fetchall()


def test_current_lease_records_observation_bound_to_generation(pg_dsn, leased):
    queue, lease, spec = leased
    assert queue.record_spark_observation(lease.run_id, lease.lease_generation, spec.tenant_id, OBSERVATION)
    assert observed(pg_dsn, lease.run_id) == [(lease.lease_generation,)]


def test_superseded_generation_cannot_publish(pg_dsn, leased):
    queue, lease, spec = leased
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("UPDATE evaluation_runs SET lease_expires_at = now() - interval '1 second' WHERE run_id=%s;", (lease.run_id,))
        conn.commit()
    newer = queue.claim_next_run(worker_id="w2")
    assert newer.lease_generation == lease.lease_generation + 1
    assert not queue.record_spark_observation(lease.run_id, lease.lease_generation, spec.tenant_id, OBSERVATION)
    assert queue.record_spark_observation(newer.run_id, newer.lease_generation, spec.tenant_id, OBSERVATION)
    assert observed(pg_dsn, lease.run_id) == [(newer.lease_generation,)]


def test_expired_lease_and_terminal_run_cannot_publish(pg_dsn, leased):
    queue, lease, spec = leased
    from dq_scoring.core.entities import RunStatus
    assert queue.complete_run(lease.run_id, lease.lease_generation, RunStatus.FAILED, "x", spec.tenant_id)
    assert not queue.record_spark_observation(lease.run_id, lease.lease_generation, spec.tenant_id, OBSERVATION)
    assert observed(pg_dsn, lease.run_id) == []


def test_wrong_tenant_cannot_publish(pg_dsn, leased):
    queue, lease, _ = leased
    assert not queue.record_spark_observation(lease.run_id, lease.lease_generation, uuid4(), OBSERVATION)


def test_concurrent_publishers_cannot_exceed_attempt_cap(pg_dsn, leased):
    queue, lease, spec = leased
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "INSERT INTO run_events (event_id,tenant_id,run_id,event_type,attempt_count,lease_generation,event_payload) "
            "SELECT gen_random_uuid(),%s,%s,'SPARK_OBSERVED',1,%s,'{}'::jsonb FROM generate_series(1,499)",
            (spec.tenant_id, lease.run_id, lease.lease_generation),
        )
    barrier = Barrier(2)

    def publish(_):
        barrier.wait()
        return queue.record_spark_observation(lease.run_id, lease.lease_generation, spec.tenant_id, OBSERVATION)

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(publish, range(2))) == [False, True]
    assert len(observed(pg_dsn, lease.run_id)) == 500


def test_publication_waits_for_terminal_transition(pg_dsn, leased):
    queue, lease, spec = leased
    with psycopg.connect(pg_dsn) as conn, ThreadPoolExecutor(1) as pool:
        conn.execute("UPDATE evaluation_runs SET run_status='FAILED' WHERE run_id=%s", (lease.run_id,))
        pending = pool.submit(queue.record_spark_observation, lease.run_id, lease.lease_generation, spec.tenant_id, OBSERVATION)
        conn.commit()
        assert pending.result(timeout=5) is False
    assert observed(pg_dsn, lease.run_id) == []
