"""Unit tests for in-memory infrastructure adapters."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.adapters.db.in_memory_assessment_store import (
    InMemoryAssessmentStore,
)
from dq_scoring.adapters.queue.in_memory_queue import InMemoryQueueAdapter
from dq_scoring.core.entities import (
    DatasetSnapshot,
    ImmutableAssessment,
    QualityRule,
    RuleExecutionOutput,
    RunSpec,
    RunStatus,
)
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.core.models import (
    PublicationStatus,
    QualityGateStatus,
    RuleCounts,
    ScoringPolicy,
)


def _sample_snapshot() -> DatasetSnapshot:
    return DatasetSnapshot(
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
        schema_definition={"c1": "string"},
        total_rows=50,
        total_columns=1,
        captured_at=datetime.now(UTC),
    )


def test_in_memory_compute_adapter():
    adapter = InMemoryComputeAdapter()
    snapshot = _sample_snapshot()
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R1",
        dimension="Completeness",
        rule_type="not_null",
    )

    # Default execution
    outs = adapter.execute_rules(snapshot, [rule])
    assert len(outs) == 1
    assert outs[0].counts.passed == 50

    # Custom preset
    adapter.set_rule_output(
        rule.rule_id,
        RuleExecutionOutput(
            rule_id=rule.rule_id,
            counts=RuleCounts(passed=40, failed=10, total_observed=50),
        ),
    )
    outs_custom = adapter.execute_rules(snapshot, [rule])
    assert outs_custom[0].counts.failed == 10

    # Outliers and profiling
    outlier = adapter.detect_outliers(snapshot, "c1")
    assert outlier.total_evaluated == 50
    metrics = adapter.profile_snapshot(snapshot, ["c1"])
    assert len(metrics) == 1
    assert metrics[0].metric_value == 50

    # Immutability registration and verification contract
    adapter.register_snapshot(snapshot)
    adapter.verify_snapshot(snapshot)
    adapter.release_snapshot(snapshot)
    with pytest.raises(RunAbortedError):
        adapter.verify_snapshot(snapshot)


def test_in_memory_assessment_store():
    store = InMemoryAssessmentStore()
    aid = uuid4()
    rid = uuid4()
    assessment = ImmutableAssessment(
        assessment_id=aid,
        tenant_id=uuid4(),
        run_id=rid,
        snapshot_id=uuid4(),
        dq_score=90.0,
        publication_status=PublicationStatus.PUBLISHED,
        coverage_ratio=0.9,
        quality_gate=QualityGateStatus.PASS,
        dimension_results=[],
        assessment_hash="hash123",
        created_at=datetime.now(UTC),
    )

    # Save with lease gen 2
    store.save_assessment_atomic(assessment, [], lease_generation=2)
    assert store.get_assessment(aid) == assessment
    assert store.get_assessment_by_run(rid) == assessment

    # Stale lease gen 1 must fail
    with pytest.raises(PermissionError):
        store.save_assessment_atomic(assessment, [], lease_generation=1)


def test_in_memory_queue_adapter():
    queue = InMemoryQueueAdapter()
    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=uuid4(),
        snapshot=_sample_snapshot(),
        rules=[],
        policy=ScoringPolicy(),
    )

    # Idempotent enqueue
    rid1 = queue.enqueue_run(spec, idempotency_key="key-1")
    rid2 = queue.enqueue_run(spec, idempotency_key="key-1")
    assert rid1 == rid2

    # Claim
    leased = queue.claim_next_run(worker_id="w1")
    assert leased is not None
    assert leased.run_id == rid1
    assert leased.lease_generation == 1

    # Heartbeat
    assert queue.heartbeat(rid1, lease_generation=1) is True
    assert queue.heartbeat(rid1, lease_generation=999) is False

    # Complete
    assert (
        queue.complete_run(rid1, lease_generation=1, status=RunStatus.SUCCEEDED) is True
    )
    assert queue.get_run_status(rid1) == RunStatus.SUCCEEDED
