"""Unit tests for EvaluationOrchestrator."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.adapters.db.in_memory_assessment_store import (
    InMemoryAssessmentStore,
)
from dq_scoring.adapters.queue.in_memory_queue import InMemoryQueueAdapter
from dq_scoring.core.entities import (
    DatasetSnapshot,
    LeasedRun,
    QualityRule,
    RunSpec,
    RunStatus,
)
from dq_scoring.core.models import PublicationStatus, QualityGateStatus, ScoringPolicy
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator


def _create_setup():
    compute = InMemoryComputeAdapter()
    store = InMemoryAssessmentStore()
    queue = InMemoryQueueAdapter()
    orchestrator = EvaluationOrchestrator(compute, store, queue)

    snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="OBJECT_FILE",
        source_descriptor={
            "bucket": "test-bucket",
            "key": "snapshots/tenant/raw.csv",
            "version_id": "v1",
            "content_sha256": "0" * 64,
            "size_bytes": 1024,
            "format": "CSV",
            "canonical": {
                "bucket": "test-bucket",
                "key": "snapshots/tenant/canonical.parquet",
                "version_id": "v1",
                "content_sha256": "0" * 64,
                "size_bytes": 1024,
                "format": "PARQUET",
            },
            "normalization_version": 1,
        },
        schema_definition={"val": "float"},
        total_rows=100,
        total_columns=1,
        captured_at=datetime.now(UTC),
    )
    compute.register_snapshot(snapshot)
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R1",
        dimension="Completeness",
        rule_type="not_null",
    )
    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=snapshot.tenant_id,
        snapshot=snapshot,
        rules=[rule],
        policy=ScoringPolicy(),
        outlier_columns=["val"],
    )
    return compute, store, queue, orchestrator, spec


def test_orchestrator_happy_path():
    _compute, store, queue, orchestrator, spec = _create_setup()
    run_id = queue.enqueue_run(spec, idempotency_key="run-1")
    leased = queue.claim_next_run(worker_id="worker-a")
    assert leased is not None
    assert leased.run_id == run_id

    assessment = orchestrator.execute_leased_run(leased)

    assert assessment.dq_score == 100.0
    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert assessment.quality_gate == QualityGateStatus.PASS
    assert assessment.assessment_hash != ""

    # Verify persisted in store
    saved = store.get_assessment(assessment.assessment_id)
    assert saved is not None
    assert saved.assessment_hash == assessment.assessment_hash

    # Verify completed in queue
    status = queue.get_run_status(run_id)
    assert status == RunStatus.SUCCEEDED


def test_orchestrator_failure_recovery():
    compute, store, queue, orchestrator, spec = _create_setup()
    queue.enqueue_run(spec, idempotency_key="run-err")
    leased = queue.claim_next_run(worker_id="worker-a")
    assert leased is not None

    # Simulate catastrophic compute error
    def _exploding_execute(*args, **kwargs):
        raise ConnectionResetError("Spark cluster unreachable")

    compute.execute_rules = _exploding_execute

    with pytest.raises(ConnectionResetError):
        orchestrator.execute_leased_run(leased)

    # Queue should be marked FAILED
    status = queue.get_run_status(leased.run_id)
    assert status == RunStatus.FAILED

    # No assessment should be persisted
    saved = store.get_assessment_by_run(leased.run_id)
    assert saved is None


def test_orchestrator_lease_fencing():
    _compute, _store, queue, orchestrator, spec = _create_setup()
    queue.enqueue_run(spec, idempotency_key="run-fence")

    # Worker 1 claims run (gen 1)
    leased1 = queue.claim_next_run(worker_id="worker-1")
    assert leased1 is not None
    assert leased1.lease_generation == 1

    # Simulate worker 1 hanging, worker 2 re-claims / lease generation bumped to 2
    # In store, simulate that lease generation 2 has already written:
    fake_assessment = orchestrator._build_and_persist_assessment(
        LeasedRun(
            run_id=leased1.run_id,
            worker_id="worker-2",
            lease_generation=2,
            claimed_at=datetime.now(UTC),
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=300),
            spec=spec,
        ),
        orchestrator._aggregator.aggregate([], spec.policy),
        [],
    )
    assert fake_assessment is not None

    # Now zombie worker 1 tries to write with old lease gen 1 -> PermissionError
    with pytest.raises(PermissionError, match="Lease fencing error"):
        orchestrator.execute_leased_run(leased1)


def test_orchestrator_heartbeat_failure_aborts_immediately():
    compute, store, queue, orchestrator, spec = _create_setup()
    queue.enqueue_run(spec, idempotency_key="run-hb-fail")
    leased = queue.claim_next_run(worker_id="worker-hb")
    assert leased is not None

    # Simulate expired lease in queue
    now = datetime.now(UTC)
    queue._active_leases[leased.run_id] = LeasedRun(
        run_id=leased.run_id,
        worker_id=leased.worker_id,
        lease_generation=leased.lease_generation,
        claimed_at=leased.claimed_at,
        lease_expires_at=now - timedelta(seconds=1),
        spec=leased.spec,
    )

    executed_rules = False

    def _should_not_run(*args, **kwargs):
        nonlocal executed_rules
        executed_rules = True
        return []

    compute.execute_rules = _should_not_run

    with pytest.raises(
        PermissionError, match="Lease fencing error: lease lost or expired"
    ):
        orchestrator.execute_leased_run(leased)

    assert not executed_rules
    assert store.get_assessment_by_run(leased.run_id) is None
    # Stale worker must NOT overwrite status to FAILED
    assert queue.get_run_status(leased.run_id) == RunStatus.RUNNING
