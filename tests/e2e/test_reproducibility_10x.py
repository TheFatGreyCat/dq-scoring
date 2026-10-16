"""T5.1: Reproducibility Replay (10x) and Source Immutability Audit (AC-013, AC-015, GATE-03, GATE-10)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import QualityRule, RunSpec
from dq_scoring.core.models import PublicationStatus, QualityGateStatus, ScoringPolicy
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker
from tests.support.run_seed import seed_run_prerequisites


def compute_file_sha256(path: Path | str) -> str:
    """Compute SHA-256 hash of a file for immutability auditing."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    """PySpark compute adapter for replay tests."""
    return PySparkComputeAdapter()


@pytest.fixture
def golden_csv_path() -> Path:
    """Path to Golden 5k dataset."""
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "tests/fixtures/chicago_taxi/chicago_taxi_golden_5k.csv"
def test_10x_reproducibility_and_immutability(
    pg_dsn: str,
    spark_adapter: PySparkComputeAdapter,
    golden_csv_path: Path,
):
    """Execute 10 consecutive evaluation iterations to prove bit-exact reproducibility and source immutability."""
    assert golden_csv_path.exists(), f"Golden dataset not found at {golden_csv_path}"

    # AC-015 / GATE-10: Baseline Source SHA-256 Hash
    initial_sha256 = compute_file_sha256(golden_csv_path)

    tenant_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()

    from tests.support.object_snapshots import create_test_snapshot
    snapshot = create_test_snapshot(golden_csv_path, tenant_id=tenant_id, asset_id=asset_id, snapshot_id=snapshot_id)

    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_COMP_01",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "trip_id"},
            is_required=True,
            is_critical=True,
            acceptance_threshold=95.0,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_COMP_02",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "fare"},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_VAL_01",
            dimension="Validity",
            rule_type="TYPE_PARSE",
            parameters={"column": "trip_start_timestamp", "data_type": "TIMESTAMP", "format": "yyyy-MM-dd HH:mm:ss"},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_VAL_02",
            dimension="Validity",
            rule_type="TYPE_PARSE",
            parameters={"column": "fare", "data_type": "DOUBLE"},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_VAL_03",
            dimension="Validity",
            rule_type="DOMAIN_RANGE",
            parameters={"column": "fare", "min_value": 0.0},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_UNIQ_01",
            dimension="Uniqueness",
            rule_type="UNIQUENESS",
            parameters={"column": "trip_id"},
            is_required=True,
        ),
    ]

    policy = ScoringPolicy(
        warn_min=60.0,
        pass_min=80.0,
        publication_threshold=0.80,
        critical_acceptance_threshold=95.0,
    )

    store = PostgresAssessmentStoreAdapter(pg_dsn)
    queue = PostgresQueueAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    assessment_hashes: list[str] = []
    dq_scores: list[float] = []
    dimension_score_maps: list[dict[str, float]] = []

    fixed_ruleset_id = uuid4()
    fixed_policy_id = uuid4()

    for iteration in range(1, 11):
        run_id = uuid4()
        spec = RunSpec(
            run_id=run_id,
            tenant_id=tenant_id,
            snapshot=snapshot,
            rules=rules,
            policy=policy,
            ruleset_id=fixed_ruleset_id,
            policy_id=fixed_policy_id,
        )

        spec = seed_run_prerequisites(pg_dsn, spec)
        queue.enqueue_run(spec, idempotency_key=f"rep-run-{iteration}-{run_id}")
        worker = EvaluationWorker(
            queue_port=queue,
            orchestrator=orchestrator,
            worker_id=f"rep-worker-{iteration}",
            poll_interval=0.01,
            heartbeat_interval=0.5,
        )
        assessment = worker.run_once()

        assert assessment is not None, f"Iteration {iteration} produced no assessment"
        assert assessment.publication_status == PublicationStatus.PUBLISHED
        assert assessment.quality_gate == QualityGateStatus.PASS
        assert assessment.dq_score is not None

        assessment_hashes.append(assessment.assessment_hash)
        dq_scores.append(assessment.dq_score)
        dimension_score_maps.append({d.dimension: d.dimension_score for d in assessment.dimension_results})

    # AC-013 & GATE-03: Assert 10/10 Bit-Exact assessment_hash match
    assert len(set(assessment_hashes)) == 1, (
        f"Assessment hash divergence across 10 runs! Hashes: {set(assessment_hashes)}"
    )

    # Assert 10/10 Bit-Exact DQ Score match
    assert len(set(dq_scores)) == 1, (
        f"DQ Score divergence across 10 runs! Scores: {set(dq_scores)}"
    )

    # Assert 10/10 Dimension Scores match
    first_dim_map = dimension_score_maps[0]
    for idx, dim_map in enumerate(dimension_score_maps[1:], start=2):
        assert dim_map == first_dim_map, f"Dimension scores divergence at iteration {idx}"

    # AC-015 & GATE-10: Verify Source File Immutability (zero byte changes)
    post_run_sha256 = compute_file_sha256(golden_csv_path)
    assert initial_sha256 == post_run_sha256, (
        f"Source file mutated! Initial: {initial_sha256}, Post: {post_run_sha256}"
    )

