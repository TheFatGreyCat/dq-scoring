"""Integration tests for EvaluationOrchestrator backed by real PostgreSQL Store and Queue adapters."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import (
    DatasetSnapshot,
    OutlierExecutionOutput,
    QualityRule,
    RuleExecutionOutput,
    RunSpec,
    RunStatus,
)
from dq_scoring.core.models import (
    MeasurementStatus,
    PublicationStatus,
    QualityGateStatus,
    RuleCounts,
)
from dq_scoring.services.evaluation_orchestrator import (
    GENERIC_RUN_FAILURE,
    EvaluationOrchestrator,
)
from tests.support.run_seed import seed_run_prerequisites


class FailingComputeAdapter(InMemoryComputeAdapter):
    """Compute engine adapter that raises technical execution errors."""

    def profile_snapshot(self, snapshot: DatasetSnapshot, columns: list[str]):
        raise RuntimeError("Compute infrastructure connection timeout")

    def execute_rules(
        self,
        snapshot: DatasetSnapshot,
        rules: list[QualityRule],
        sample_limit: int = 50,
    ) -> list[RuleExecutionOutput]:
        raise RuntimeError("Spark cluster fatal worker crash")

    def detect_outliers(
        self,
        snapshot: DatasetSnapshot,
        column: str,
        k: float = 1.5,
        sample_limit: int = 50,
    ) -> OutlierExecutionOutput:
        raise RuntimeError("Spark outlier computation failed")
def test_orchestrator_postgres_end_to_end_happy_path(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify orchestrator runs complete lifecycle through PostgreSQL store and queue."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)
    compute = InMemoryComputeAdapter()

    for rule in sample_run_spec.rules:
        compute.set_rule_output(
            rule.rule_id,
            RuleExecutionOutput(
                rule_id=rule.rule_id,
                counts=RuleCounts(
                    passed=100,
                    failed=0,
                    missing=0,
                    miscast=0,
                    not_applicable=0,
                    total_observed=100,
                ),
                status=MeasurementStatus.MEASURED,
            ),
        )

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    compute.register_snapshot(sample_run_spec.snapshot)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"orch-test-{uuid4()}")
    leased_run = queue.claim_next_run(worker_id="worker-orch-integration")
    assert leased_run is not None

    orchestrator = EvaluationOrchestrator(
        compute_engine=compute,
        assessment_store=store,
        queue_port=queue,
    )

    assessment = orchestrator.execute_leased_run(leased_run)

    assert assessment.publication_status == PublicationStatus.PUBLISHED
    assert assessment.quality_gate == QualityGateStatus.PASS
    assert assessment.dq_score == pytest.approx(100.0)

    retrieved = store.get_assessment(assessment.assessment_id, tenant_id=sample_run_spec.tenant_id)
    assert retrieved is not None
    assert retrieved.assessment_id == assessment.assessment_id

    assert queue.get_run_status(sample_run_spec.run_id, tenant_id=sample_run_spec.tenant_id) == RunStatus.SUCCEEDED

    set_tenant_context(db_conn, sample_run_spec.tenant_id)
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM run_events WHERE run_id = %s ORDER BY created_at ASC;",
            (sample_run_spec.run_id,),
        )
        events = [r[0] for r in cur.fetchall()]
        assert "RUN_QUEUED" in events
        assert "RUN_SUCCEEDED" in events



def test_orchestrator_postgres_lease_lost_prevents_publication(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify orchestrator aborts execution when lease generation is stolen/superseded."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)
    compute = InMemoryComputeAdapter()

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    compute.register_snapshot(sample_run_spec.snapshot)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"orch-fencing-{uuid4()}")
    leased_run = queue.claim_next_run(worker_id="worker-orch-zombie")
    assert leased_run is not None

    set_tenant_context(db_conn, sample_run_spec.tenant_id)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluation_runs
            SET lease_generation = lease_generation + 1,
                lease_owner = 'worker-orch-usurper'
            WHERE run_id = %s;
            """,
            (sample_run_spec.run_id,),
        )
        db_conn.commit()

    orchestrator = EvaluationOrchestrator(
        compute_engine=compute,
        assessment_store=store,
        queue_port=queue,
    )

    with pytest.raises(PermissionError, match="Lease fencing error"):
        orchestrator.execute_leased_run(leased_run)

    assessment = store.get_assessment_by_run(sample_run_spec.run_id)
    assert assessment is None


def test_orchestrator_postgres_technical_failure_marks_run_failed(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify global technical failure transitions run to FAILED without publishing score."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)
    failing_compute = FailingComputeAdapter()

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    failing_compute.register_snapshot(sample_run_spec.snapshot)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"orch-fail-{uuid4()}")
    leased_run = queue.claim_next_run(worker_id="worker-orch-fail")
    assert leased_run is not None

    orchestrator = EvaluationOrchestrator(
        compute_engine=failing_compute,
        assessment_store=store,
        queue_port=queue,
    )

    with pytest.raises(RuntimeError, match="Spark cluster fatal worker crash"):
        orchestrator.execute_leased_run(leased_run)

    assert queue.get_run_status(sample_run_spec.run_id, tenant_id=sample_run_spec.tenant_id) == RunStatus.FAILED
    assert store.get_assessment_by_run(sample_run_spec.run_id) is None

    set_tenant_context(db_conn, sample_run_spec.tenant_id)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, event_payload FROM run_events
            WHERE run_id = %s AND event_type = 'RUN_FAILED';
            """,
            (sample_run_spec.run_id,),
        )
        row = cur.fetchone()
        assert row is not None
        # Safe outputs: internal exception text stays in worker logs, never in run records.
        assert row[1] == {"error": GENERIC_RUN_FAILURE}
        cur.execute("SELECT execution_error FROM evaluation_runs WHERE run_id = %s;", (sample_run_spec.run_id,))
        assert cur.fetchone()[0] == GENERIC_RUN_FAILURE
