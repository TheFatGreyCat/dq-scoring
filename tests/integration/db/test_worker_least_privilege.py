"""Regression test: the worker completes a run as a non-superuser login (H1).

Under RLS a plain dq_app_role login cannot see other tenants' QUEUED runs, so the
documented worker setup left every run in QUEUED forever.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import RunStatus
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker
from tests.integration.db.test_role_isolation import _make_spec, _seed_tenant
from tests.support.run_seed import seed_run_prerequisites

WORKER_LOGIN = "dq_worker_test_user"
WORKER_PASSWORD = "synthetic-worker-password"


@pytest.fixture
def worker_dsn(pg_dsn: str) -> str:
    """A LOGIN role provisioned exactly as the deployment guide prescribes for workers."""
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(f"DROP ROLE IF EXISTS {WORKER_LOGIN};")
        conn.execute(
            f"CREATE ROLE {WORKER_LOGIN} LOGIN PASSWORD '{WORKER_PASSWORD}' "
            "NOSUPERUSER NOBYPASSRLS IN ROLE dq_worker_role;"
        )
    info = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    info.update(user=WORKER_LOGIN, password=WORKER_PASSWORD)
    yield psycopg.conninfo.make_conninfo(**info)
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(f"DROP OWNED BY {WORKER_LOGIN}; DROP ROLE IF EXISTS {WORKER_LOGIN};")


def test_worker_claims_and_completes_run_as_least_privilege_login(pg_dsn: str, worker_dsn: str) -> None:
    tenant_id = uuid4()
    with psycopg.connect(pg_dsn) as admin:
        _seed_tenant(admin, tenant_id)
        admin.commit()
    spec = _make_spec(tenant_id)
    spec = seed_run_prerequisites(pg_dsn, spec)
    PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(spec, idempotency_key=f"lp-{uuid4()}")

    compute = InMemoryComputeAdapter()
    compute.register_snapshot(spec.snapshot)
    queue = PostgresQueueAdapter(dsn=worker_dsn)
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=EvaluationOrchestrator(
            compute_engine=compute,
            assessment_store=PostgresAssessmentStoreAdapter(dsn=worker_dsn),
            queue_port=queue,
        ),
        worker_id="least-privilege-worker",
        heartbeat_interval=0.2,
    )
    assessment = worker.run_once()

    assert assessment is not None
    assert PostgresQueueAdapter(dsn=pg_dsn).get_run_status(spec.run_id) == RunStatus.SUCCEEDED
