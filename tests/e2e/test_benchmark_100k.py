"""T5.2: 100k Events Benchmark Performance Test (NFR-PERF-001..003, AC-014)."""

from __future__ import annotations

import time
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


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    """PySpark compute adapter for benchmark tests."""
    return PySparkComputeAdapter()


def test_100k_benchmark_performance_and_sla(
    pg_dsn: str,
    spark_adapter: PySparkComputeAdapter,
    benchmark_csv_path: Path,
):
    """Execute end-to-end evaluation on 100k records dataset and assert performance within SLA."""
    assert benchmark_csv_path.exists(), f"Benchmark dataset not found at {benchmark_csv_path}"

    tenant_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    run_id = uuid4()

    from tests.support.object_snapshots import create_test_snapshot
    snapshot = create_test_snapshot(benchmark_csv_path, tenant_id=tenant_id, asset_id=asset_id, snapshot_id=snapshot_id)

    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code="BM_COMP_01",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "trip_id"},
            is_required=True,
            is_critical=True,
            acceptance_threshold=95.0,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="BM_COMP_02",
            dimension="Completeness",
            rule_type="NON_NULL",
            parameters={"column": "fare"},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="BM_VAL_01",
            dimension="Validity",
            rule_type="TYPE_PARSE",
            parameters={"column": "trip_start_timestamp", "data_type": "TIMESTAMP", "format": "yyyy-MM-dd HH:mm:ss"},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="BM_VAL_02",
            dimension="Validity",
            rule_type="TYPE_PARSE",
            parameters={"column": "fare", "data_type": "DOUBLE"},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="BM_VAL_03",
            dimension="Validity",
            rule_type="DOMAIN_RANGE",
            parameters={"column": "fare", "min_value": 0.0},
            is_required=True,
        ),
        QualityRule(
            rule_id=uuid4(),
            rule_code="BM_UNIQ_01",
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

    spec = RunSpec(
        run_id=run_id,
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=rules,
        policy=policy,
        execution_profile="SPARK_K3S",
    )

    store = PostgresAssessmentStoreAdapter(pg_dsn)
    queue = PostgresQueueAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )

    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"bm-run-{run_id}")
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="benchmark-worker-100k",
        poll_interval=0.01,
        heartbeat_interval=0.5,
    )

    # Measure End-to-End SLA time
    start_time = time.perf_counter()
    assessment = worker.run_once()
    duration = time.perf_counter() - start_time

    # Assertions
    assert assessment is not None
    assert assessment.run_id == run_id
    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert assessment.quality_gate in (QualityGateStatus.PASS, QualityGateStatus.WARN)
    assert assessment.dq_score is not None
    assert assessment.dq_score > 0.0

    # Verify duration meets target benchmark SLA (target <= 120s)
    throughput = 100000 / duration
    print(f"\n[BENCHMARK RESULT] 100k records processed in {duration:.2f}s (Throughput: {throughput:.0f} rows/s, DQ Score: {assessment.dq_score:.2f})")
    assert duration <= 120.0, f"Benchmark execution took {duration:.2f}s, exceeding 120s SLA"

@pytest.fixture(scope="session")
def benchmark_csv_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the seeded 100k benchmark in the session temporary directory."""
    out_dir = tmp_path_factory.mktemp("benchmark")
    target = out_dir / "chicago_taxi_benchmark_100k.csv"
    from scripts.generate_fixtures import write_dataset_csv
    write_dataset_csv(target, 100000, is_golden=False)
    return target
