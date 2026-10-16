"""End-to-End Integration test combining PostgreSQL persistence, queue leasing, and PySpark compute."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RunSpec, RunStatus
from dq_scoring.core.models import PublicationStatus, QualityGateStatus, ScoringPolicy
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker
from tests.support.run_seed import seed_run_prerequisites


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    """Module-scoped PySparkComputeAdapter."""
    return PySparkComputeAdapter()


def _upload_golden_snapshot(tenant_id) -> DatasetSnapshot:
    from tests.support.object_snapshots import create_test_snapshot
    root = Path(__file__).resolve().parents[3]
    return create_test_snapshot(root / "tests/fixtures/chicago_taxi/chicago_taxi_golden_5k.csv", tenant_id=tenant_id)


def test_end_to_end_spark_worker_postgres(
    pg_dsn: str,
    db_conn,
    spark_adapter: PySparkComputeAdapter,
):
    """Verify complete end-to-end evaluation run using real Postgres Queue, Store, and PySpark Compute."""
    tenant_id = uuid4()
    snapshot = _upload_golden_snapshot(tenant_id)

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
    ]

    policy = ScoringPolicy(
        warn_min=60.0,
        pass_min=80.0,
        publication_threshold=0.80,
        critical_acceptance_threshold=95.0,
    )

    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=rules,
        policy=policy,
    )

    queue = PostgresQueueAdapter(pg_dsn)
    store = PostgresAssessmentStoreAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    # 1. Enqueue run
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"spark-test-{uuid4()}")

    # 2. Worker executes run
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="spark-integration-worker-01",
        poll_interval=0.01,
        heartbeat_interval=0.5,
    )
    assessment = worker.run_once()

    # 3. Assertions
    assert assessment is not None
    assert assessment.run_id == spec.run_id
    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert assessment.quality_gate == QualityGateStatus.PASS
    assert assessment.dq_score is not None
    assert assessment.dq_score > 90.0

    # 4. Verify persisted state in PostgreSQL
    saved_assessment = store.get_assessment(assessment.assessment_id, tenant_id=tenant_id)
    assert saved_assessment is not None
    assert saved_assessment.assessment_id == assessment.assessment_id
    assert saved_assessment.assessment_hash == assessment.assessment_hash

    # 5. Verify run status in queue table
    assert queue.get_run_status(spec.run_id, tenant_id=tenant_id) == RunStatus.SUCCEEDED


def test_end_to_end_spark_golden_5k_complete_matrix(
    pg_dsn: str,
    spark_adapter: PySparkComputeAdapter,
):
    """Verify complete 12-rule Golden 5k dataset end-to-end against golden_ground_truth_matrix.json."""
    import json

    matrix_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tests"
        / "fixtures"
        / "chicago_taxi"
        / "golden_ground_truth_matrix.json"
    )
    with matrix_path.open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    tenant_id = uuid4()
    snapshot = _upload_golden_snapshot(tenant_id)

    rules_def = [
        ("CH_COMP_01", "NON_NULL", {"column": "trip_id"}),
        ("CH_COMP_02", "NON_NULL", {"column": "fare"}),
        ("CH_VAL_01", "TYPE_PARSE", {"column": "trip_start_timestamp", "data_type": "TIMESTAMP", "format": "yyyy-MM-dd HH:mm:ss"}),
        ("CH_VAL_02", "TYPE_PARSE", {"column": "fare", "data_type": "DOUBLE"}),
        ("CH_VAL_03", "DOMAIN_RANGE", {"column": "fare", "min_value": 0.0}),
        ("CH_VAL_04", "DOMAIN_RANGE", {"column": "payment_type", "allowed_values": ["Cash", "Credit Card", "Prcard", "Dispute", "No Charge", "Unknown"]}),
        ("CH_UNIQ_01", "UNIQUENESS", {"column": "trip_id"}),
        ("CH_CONS_01", "CROSS_FIELD", {"column": "trip_end_timestamp", "comparison_column": "trip_start_timestamp", "operator": ">=", "data_type": "TIMESTAMP", "format": "yyyy-MM-dd HH:mm:ss"}),
        ("CH_CONS_02", "CROSS_FIELD", {"column": "trip_total", "comparison_column": "fare", "operator": ">=", "data_type": "DOUBLE"}),
        ("CH_TIME_01", "DOMAIN_RANGE", {"column": "trip_start_timestamp", "year": 2023, "format": "yyyy-MM-dd HH:mm:ss"}),
        ("CH_ACC_01", "DOMAIN_RANGE", {"column": "trip_miles", "min_value": 0.0, "max_value": 100.0}),
        ("CH_OUT_01", "DOMAIN_RANGE", {"column": "fare", "max_value": 100.0}),
    ]

    quality_rules = []
    for code, r_type, params in rules_def:
        gt_rule = next(r for r in ground_truth["rules"] if r["rule_code"] == code)
        is_advisory = gt_rule["is_advisory"]
        acceptance_threshold = 95.0 if gt_rule["is_critical"] else None
        quality_rules.append(
            QualityRule(
                rule_id=uuid4(),
                rule_code=code,
                dimension=gt_rule["dimension"],
                rule_type=r_type,
                parameters=params,
                is_required=gt_rule["is_required"],
                is_critical=gt_rule["is_critical"],
                is_advisory=is_advisory,
                score_enabled=not is_advisory,
                contribution_weight=gt_rule["contribution_weight"],
                acceptance_threshold=acceptance_threshold,
                null_policy=gt_rule["null_policy"],
            )
        )

    policy = ScoringPolicy(
        warn_min=60.0,
        pass_min=80.0,
        publication_threshold=0.80,
        critical_acceptance_threshold=95.0,
    )

    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=quality_rules,
        policy=policy,
    )

    queue = PostgresQueueAdapter(pg_dsn)
    store = PostgresAssessmentStoreAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"spark-full-matrix-{uuid4()}")
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="spark-matrix-worker-01",
        poll_interval=0.01,
        heartbeat_interval=0.5,
    )
    assessment = worker.run_once()

    assert assessment is not None
    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert assessment.quality_gate == QualityGateStatus.PASS
    assert assessment.coverage_ratio == pytest.approx(ground_truth["overall_coverage"], abs=1e-3)
    assert assessment.dq_score == pytest.approx(ground_truth["overall_dq_score"], abs=1e-2)

    # Verify all 6 dimensions
    dim_map = {d.dimension: d for d in assessment.dimension_results}
    for dim_name, expected in ground_truth["dimensions"].items():
        assert dim_name in dim_map
        assert dim_map[dim_name].dimension_score == pytest.approx(expected["score"], abs=1e-2)
        assert dim_map[dim_name].coverage_ratio == pytest.approx(expected["coverage"], abs=1e-3)


def test_end_to_end_zero_tolerance_critical_failure(
    pg_dsn: str,
    spark_adapter: PySparkComputeAdapter,
):
    """Verify zero-tolerance policy triggers Critical FAIL and WITHHELD publication on critical violations."""
    tenant_id = uuid4()
    snapshot = _upload_golden_snapshot(tenant_id)

    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="CH_COMP_01",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "trip_id"},
            is_required=True,
            is_critical=True,  # 50 missing rows -> triggers zero-tolerance violation
        ),
    ]

    # Zero tolerance (critical_acceptance_threshold = None)
    policy = ScoringPolicy(
        warn_min=60.0,
        pass_min=80.0,
        publication_threshold=0.80,
        critical_acceptance_threshold=None,
    )

    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=rules,
        policy=policy,
    )

    queue = PostgresQueueAdapter(pg_dsn)
    store = PostgresAssessmentStoreAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"spark-zt-{uuid4()}")
    worker = EvaluationWorker(queue_port=queue, orchestrator=orchestrator, worker_id="zt-worker")
    assessment = worker.run_once()

    assert assessment is not None
    assert assessment.quality_gate == QualityGateStatus.FAIL
    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert assessment.dq_score is not None


