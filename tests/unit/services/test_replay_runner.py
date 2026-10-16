"""Unit tests for ReplayRunner verifying deterministic reproducibility (GATE-03 / NFR-COR-001)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
)
from dq_scoring.core.models import ScoringPolicy
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.services.replay_runner import ReplayRunner


def test_replay_runner_deterministic_parity():
    compute = InMemoryComputeAdapter()
    store = InMemoryAssessmentStore()
    queue = InMemoryQueueAdapter()
    orchestrator = EvaluationOrchestrator(compute, store, queue)
    runner = ReplayRunner(orchestrator)

    snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="OBJECT_FILE",
        source_descriptor={
            "bucket": "lakehouse",
            "key": "snapshots/tenant/raw.parquet",
            "version_id": "v1",
            "content_sha256": "0" * 64,
            "size_bytes": 1024,
            "format": "PARQUET",
            "canonical": {
                "bucket": "lakehouse",
                "key": "snapshots/tenant/canonical.parquet",
                "version_id": "v1",
                "content_sha256": "0" * 64,
                "size_bytes": 1024,
                "format": "PARQUET",
            },
            "normalization_version": 1,
        },
        schema_definition={"amt": "float"},
        total_rows=1000,
        total_columns=1,
        captured_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
    )
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
    )

    now = datetime.now(UTC)
    run1 = LeasedRun(
        run_id=spec.run_id,
        worker_id="w1",
        lease_generation=1,
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=300),
        spec=spec,
    )
    compute.register_snapshot(spec.snapshot)
    res1 = runner.replay(run1)
    assert res1.is_replay_identical is True
    first_hash = res1.actual_hash

    # Replay second time with new lease generation
    run2 = LeasedRun(
        run_id=spec.run_id,
        worker_id="w2",
        lease_generation=2,
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=300),
        spec=spec,
    )
    compute.register_snapshot(spec.snapshot)
    res2 = runner.replay(run2, expected_hash=first_hash)
    assert res2.is_replay_identical is True
    assert res2.actual_hash == first_hash


def test_replay_runner_tamper_alarm():
    compute = InMemoryComputeAdapter()
    store = InMemoryAssessmentStore()
    queue = InMemoryQueueAdapter()
    orchestrator = EvaluationOrchestrator(compute, store, queue)
    runner = ReplayRunner(orchestrator)

    snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="OBJECT_FILE",
        source_descriptor={
            "bucket": "lakehouse",
            "key": "snapshots/tenant/raw.parquet",
            "version_id": "v1",
            "content_sha256": "0" * 64,
            "size_bytes": 1024,
            "format": "PARQUET",
            "canonical": {
                "bucket": "lakehouse",
                "key": "snapshots/tenant/canonical.parquet",
                "version_id": "v1",
                "content_sha256": "0" * 64,
                "size_bytes": 1024,
                "format": "PARQUET",
            },
            "normalization_version": 1,
        },
        schema_definition={"amt": "float"},
        total_rows=1000,
        total_columns=1,
        captured_at=datetime.now(UTC),
    )
    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=snapshot.tenant_id,
        snapshot=snapshot,
        rules=[],
        policy=ScoringPolicy(),
    )
    now = datetime.now(UTC)
    leased = LeasedRun(
        run_id=spec.run_id,
        worker_id="w1",
        lease_generation=1,
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=300),
        spec=spec,
    )
    compute.register_snapshot(spec.snapshot)
    res = runner.replay(leased, expected_hash="fake-tampered-hash-value")
    assert res.is_replay_identical is False
    assert res.actual_hash != "fake-tampered-hash-value"
