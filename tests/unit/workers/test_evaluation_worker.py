"""Unit tests for EvaluationWorker and HeartbeatController."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.core.entities import (
    DatasetSnapshot,
    ImmutableAssessment,
    LeasedRun,
    QualityRule,
    RunSpec,
    RunStatus,
)
from dq_scoring.core.models import PublicationStatus, ScoringPolicy
from dq_scoring.ports.assessment_store import IAssessmentStorePort
from dq_scoring.ports.queue_port import IQueuePort
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker, HeartbeatController


class MockQueuePort(IQueuePort):
    """In-memory queue for worker unit tests."""

    def __init__(self, runs: list[LeasedRun] | None = None) -> None:
        self.queue: list[LeasedRun] = list(runs or [])
        self.heartbeat_calls: list[tuple[uuid4, int]] = []
        self.completed_runs: list[tuple[uuid4, RunStatus]] = []
        self.heartbeat_return_value: bool = True

    def claim_next_run(self, worker_id: str, timeout_seconds: int = 300) -> LeasedRun | None:
        if self.queue:
            return self.queue.pop(0)
        return None

    def heartbeat(self, run_id, lease_generation: int, tenant_id=None) -> bool:
        self.heartbeat_calls.append((run_id, lease_generation))
        return self.heartbeat_return_value

    def complete_run(self, run_id, lease_generation: int, status: RunStatus, error_message=None, tenant_id=None) -> bool:
        self.completed_runs.append((run_id, status))
        return True

    def enqueue_run(self, spec: RunSpec, idempotency_key: str = "") -> uuid4:
        return spec.run_id


class MockAssessmentStore(IAssessmentStorePort):
    """In-memory store for worker unit tests."""

    def __init__(self) -> None:
        self.saved: list[ImmutableAssessment] = []

    def save_assessment_atomic(self, assessment: ImmutableAssessment, rule_results, lease_generation: int) -> None:
        self.saved.append(assessment)

    def get_assessment_by_run(self, run_id):
        return None

    def get_latest_assessment(self, snapshot_id):
        return None


@pytest.fixture
def sample_leased_run() -> LeasedRun:
    """Fixture providing a sample LeasedRun entity."""
    tenant_id = uuid4()
    snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=tenant_id,
        asset_id=uuid4(),
        source_kind="OBJECT_FILE",
        source_descriptor={
            "bucket": "test-bucket",
            "key": f"snapshots/{tenant_id}/raw.csv",
            "version_id": "v1",
            "content_sha256": "0" * 64,
            "size_bytes": 1024,
            "format": "CSV",
            "canonical": {
                "bucket": "test-bucket",
                "key": f"snapshots/{tenant_id}/canonical.parquet",
                "version_id": "v1",
                "content_sha256": "0" * 64,
                "size_bytes": 1024,
                "format": "PARQUET",
            },
            "normalization_version": 1,
        },
        schema_definition={},
        total_rows=100,
        total_columns=2,
        captured_at=datetime.now(UTC),
    )
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="TEST_01",
        dimension="Completeness",
        rule_type="NON_NULL",
        parameters={"column": "fare"},
    )
    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=[rule],
        policy=ScoringPolicy(),
    )
    return LeasedRun(
        run_id=spec.run_id,
        worker_id="test-worker",
        lease_generation=1,
        claimed_at=datetime.now(UTC),
        lease_expires_at=datetime.now(UTC),
        spec=spec,
    )


def test_heartbeat_controller_lifecycle(sample_leased_run: LeasedRun):
    """Verify HeartbeatController periodically renews lease and stops cleanly."""
    queue = MockQueuePort()
    hb = HeartbeatController(queue_port=queue, leased_run=sample_leased_run, interval_seconds=0.05)
    hb.start()
    time.sleep(0.15)
    hb.stop()

    assert len(queue.heartbeat_calls) >= 2
    assert not hb.is_lease_lost


def test_heartbeat_controller_lease_lost(sample_leased_run: LeasedRun):
    """Verify HeartbeatController detects lease loss and notifies callback."""
    queue = MockQueuePort()
    queue.heartbeat_return_value = False
    callback_called = False

    def on_lost():
        nonlocal callback_called
        callback_called = True

    hb = HeartbeatController(
        queue_port=queue,
        leased_run=sample_leased_run,
        interval_seconds=0.02,
        on_lease_lost=on_lost,
    )
    hb.start()
    time.sleep(0.08)
    hb.stop()

    assert hb.is_lease_lost
    assert callback_called


def test_evaluation_worker_run_once_success(sample_leased_run: LeasedRun):
    """Verify EvaluationWorker claims run, executes it, and returns assessment."""
    queue = MockQueuePort(runs=[sample_leased_run])
    store = MockAssessmentStore()
    compute = InMemoryComputeAdapter()
    compute.register_snapshot(sample_leased_run.spec.snapshot)
    orchestrator = EvaluationOrchestrator(
        compute_engine=compute,
        assessment_store=store,
        queue_port=queue,
    )
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="worker-01",
        poll_interval=0.01,
        heartbeat_interval=0.05,
    )

    assessment = worker.run_once()
    assert assessment is not None
    assert assessment.run_id == sample_leased_run.run_id
    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert len(store.saved) == 1
    assert len(queue.completed_runs) == 1
    assert queue.completed_runs[0] == (sample_leased_run.run_id, RunStatus.SUCCEEDED)


def test_evaluation_worker_run_once_empty_queue():
    """Verify EvaluationWorker returns None when queue is empty."""
    queue = MockQueuePort(runs=[])
    store = MockAssessmentStore()
    compute = InMemoryComputeAdapter()
    orchestrator = EvaluationOrchestrator(
        compute_engine=compute,
        assessment_store=store,
        queue_port=queue,
    )
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="worker-01",
    )

    assessment = worker.run_once()
    assert assessment is None


def test_evaluation_worker_run_loop_bounded(sample_leased_run: LeasedRun):
    """Verify EvaluationWorker run_loop completes bounded iterations."""
    queue = MockQueuePort(runs=[sample_leased_run])
    store = MockAssessmentStore()
    compute = InMemoryComputeAdapter()
    compute.register_snapshot(sample_leased_run.spec.snapshot)
    orchestrator = EvaluationOrchestrator(
        compute_engine=compute,
        assessment_store=store,
        queue_port=queue,
    )
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="worker-01",
        poll_interval=0.01,
    )

    iterations = worker.run_loop(max_iterations=2)
    assert iterations == 2
    assert len(store.saved) == 1

