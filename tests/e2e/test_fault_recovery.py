"""T5.3: Chaos Engineering & Fault Recovery Drills (AC-006, GATE-07)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pyspark.errors import AnalysisException

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RunSpec, RunStatus
from dq_scoring.core.models import PublicationStatus, ScoringPolicy
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker
from tests.support.run_seed import seed_run_prerequisites


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    """PySpark compute adapter."""
    return PySparkComputeAdapter()


def test_fault_containment_on_unreadable_storage(
    pg_dsn: str,
    spark_adapter: PySparkComputeAdapter,
):
    """AC-006: Simulate missing/corrupt storage path -> transitions to FAILED, zero assessment published."""
    tenant_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    run_id = uuid4()

    snapshot = DatasetSnapshot(
        snapshot_id=snapshot_id,
        tenant_id=tenant_id,
        asset_id=asset_id,
        source_kind="LOCAL_FILE",
        source_descriptor={"path": "/non_existent/directory/invalid_file.csv", "format": "CSV"},
        schema_definition={"columns": ["trip_id", "fare"]},
        total_rows=100,
        total_columns=2,
        captured_at=datetime.now(UTC),
    )

    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="R1_FAIL",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "trip_id"},
            is_required=True,
        )
    ]

    policy = ScoringPolicy(
        warn_min=60.0,
        pass_min=80.0,
        publication_threshold=0.80,
    )

    spec = RunSpec(
        run_id=run_id,
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=rules,
        policy=policy,
    )

    store = PostgresAssessmentStoreAdapter(pg_dsn)
    queue = PostgresQueueAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"fault-test-{uuid4()}")
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="fault-worker-01",
        poll_interval=0.01,
        heartbeat_interval=0.5,
    )
    # Missing storage is refused before Spark reads it (ValueError) or by Spark itself.
    with pytest.raises((AnalysisException, RuntimeError, OSError, ValueError)):
        worker.run_once()

    # Assert run is marked FAILED in queue and zero assessment published
    status = queue.get_run_status(run_id)
    assert status == RunStatus.FAILED

    assessment_in_store = store.get_assessment_by_run(run_id, tenant_id=tenant_id)
    assert assessment_in_store is None


def test_worker_crash_and_lease_reclaim_drill(
    pg_dsn: str,
    spark_adapter: PySparkComputeAdapter,
):
    """GATE-07: Simulate worker SIGKILL crash during processing, verify lease expiration reclaim within <= 30s."""
    golden_csv = Path(__file__).resolve().parents[2] / "tests/fixtures/chicago_taxi/chicago_taxi_golden_5k.csv"

    tenant_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    run_id = uuid4()
    ruleset_id = uuid4()
    policy_id = uuid4()

    from tests.support.object_snapshots import create_test_snapshot
    snapshot = create_test_snapshot(golden_csv, tenant_id=tenant_id, asset_id=asset_id, snapshot_id=snapshot_id)

    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="R1_RECLAIM",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "trip_id"},
            is_required=True,
        )
    ]

    policy = ScoringPolicy(
        warn_min=60.0,
        pass_min=80.0,
        publication_threshold=0.80,
    )

    spec = RunSpec(
        run_id=run_id,
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=rules,
        policy=policy,
        ruleset_id=ruleset_id,
        policy_id=policy_id,
    )

    queue = PostgresQueueAdapter(pg_dsn)
    store = PostgresAssessmentStoreAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    # 1. Enqueue Run
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"reclaim-drill-{uuid4()}")

    # 2. Worker 1 acquires short lease (1 second timeout)
    leased_run_1 = queue.claim_next_run(
        worker_id="crashed-worker-01",
        timeout_seconds=1,
    )
    assert leased_run_1 is not None
    assert leased_run_1.run_id == run_id
    assert leased_run_1.lease_generation == 1

    # 3. Simulate Worker 1 SIGKILL crash: worker stops execution without heartbeat
    # Wait for lease to expire (> 1.0s, well within GATE-07 30s timeout)
    time.sleep(1.2)

    # 4. Worker 2 successfully reclaims the expired run with bumped monotonic lease generation
    leased_run_2 = queue.claim_next_run(
        worker_id="healthy-worker-02",
        timeout_seconds=60,
    )
    assert leased_run_2 is not None
    assert leased_run_2.run_id == run_id
    assert leased_run_2.lease_generation == 2

    # 5. Worker 2 executes run to completion
    assessment = orchestrator.execute_leased_run(leased_run_2)
    assert assessment is not None
    assert assessment.publication_status == PublicationStatus.PUBLISHED

    # 6. Verify run status is SUCCEEDED and assessment is in store
    assert queue.get_run_status(run_id) == RunStatus.SUCCEEDED
    saved_assessment = store.get_assessment(assessment.assessment_id)
    assert saved_assessment is not None

