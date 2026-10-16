"""Integration tests for PostgresAssessmentStoreAdapter and immutable WORM triggers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.errors import RaiseException

from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import ImmutableAssessment, RunSpec, RunStatus
from dq_scoring.core.models import (
    DimensionResult,
    MeasurementStatus,
    PublicationStatus,
    QualityGateStatus,
    QualityRuleResult,
    RuleCounts,
)
from dq_scoring.core.outlier_advisory import (
    OutlierResultInput,
    build_outlier_advisory_result,
)
from tests.support.run_seed import seed_run_prerequisites


def _build_test_assessment(
    tenant_id: UUID,
    run_id: UUID,
    snapshot_id: UUID,
    rule_ids: list[UUID] | None = None,
) -> tuple[ImmutableAssessment, list[QualityRuleResult]]:
    aid = uuid4()
    r1_id = rule_ids[0] if rule_ids and len(rule_ids) > 0 else uuid4()
    r2_id = rule_ids[1] if rule_ids and len(rule_ids) > 1 else uuid4()

    rule_results = [
        QualityRuleResult(
            rule_id=str(r1_id),
            dimension="COMPLETENESS",
            measurement_status=MeasurementStatus.MEASURED,
            counts=RuleCounts(
                passed=95,
                failed=5,
                missing=0,
                miscast=0,
                not_applicable=0,
                total_observed=100,
            ),
            computed_score=95.0,
            violations_count=5,
            evidence_samples=[{"id": 42, "val": None}],
        ),
        QualityRuleResult(
            rule_id=str(r2_id),
            dimension="VALIDITY",
            measurement_status=MeasurementStatus.MEASURED,
            counts=RuleCounts(
                passed=90,
                failed=10,
                missing=0,
                miscast=0,
                not_applicable=0,
                total_observed=100,
            ),
            computed_score=90.0,
            violations_count=10,
            error_message="10 rows failed range check",
        ),
    ]

    dim_results = [
        DimensionResult(
            dimension="COMPLETENESS",
            dimension_score=95.0,
            coverage_ratio=1.0,
            rule_results=[rule_results[0]],
            dimension_weight=2.0,
        ),
        DimensionResult(
            dimension="VALIDITY",
            dimension_score=90.0,
            coverage_ratio=1.0,
            rule_results=[rule_results[1]],
            dimension_weight=1.5,
        ),
    ]

    assessment = ImmutableAssessment(
        assessment_id=aid,
        tenant_id=tenant_id,
        run_id=run_id,
        snapshot_id=snapshot_id,
        dq_score=92.5,
        publication_status=PublicationStatus.PUBLISHED,
        coverage_ratio=1.0,
        quality_gate=QualityGateStatus.PASS,
        dimension_results=dim_results,
        assessment_hash="hash-123456",
        created_at=datetime.now(UTC),
        confidence_status="NOT_APPLICABLE",
    )
    return assessment, rule_results


def test_save_and_retrieve_assessment_atomic(
    pg_dsn: str, sample_run_spec: RunSpec
) -> None:
    """Verify atomic persistence of scorecard, dimensions, rule results, and outbox."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"store-test-{uuid4()}")
    leased = queue.claim_next_run(worker_id="worker-store-1")
    assert leased is not None

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, rule_results = _build_test_assessment(
        sample_run_spec.tenant_id,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )

    store.save_assessment_atomic(
        assessment=assessment,
        rule_results=rule_results,
        lease_generation=leased.lease_generation,
    )

    retrieved = store.get_assessment(assessment.assessment_id)
    assert retrieved is not None
    assert retrieved.assessment_id == assessment.assessment_id
    assert retrieved.tenant_id == sample_run_spec.tenant_id
    assert retrieved.dq_score == pytest.approx(92.5)
    assert retrieved.quality_gate == QualityGateStatus.PASS
    assert retrieved.publication_status == PublicationStatus.PUBLISHED
    assert retrieved.confidence_status == "NOT_APPLICABLE"
    assert len(retrieved.dimension_results) == 2
    dim_map = {d.dimension.upper(): d for d in retrieved.dimension_results}
    assert dim_map["COMPLETENESS"].dimension_weight == 2.0
    assert dim_map["VALIDITY"].dimension_weight == 1.5

    by_run = store.get_assessment_by_run(sample_run_spec.run_id)
    assert by_run is not None
    assert by_run.assessment_id == assessment.assessment_id

    results = store.get_rule_results(assessment.assessment_id)
    assert len(results) == 2
    assert {r.dimension.upper() for r in results} == {"COMPLETENESS", "VALIDITY"}
    rule_map = {r.dimension.upper(): r for r in results}
    assert rule_map["COMPLETENESS"].counts.passed == 95
    assert rule_map["COMPLETENESS"].counts.failed == 5
    assert rule_map["COMPLETENESS"].counts.total_observed == 100
    assert rule_map["COMPLETENESS"].evidence_samples == [{"id": 42, "val": None}]
    assert rule_map["COMPLETENESS"].rule_config_hash is not None
    assert rule_map["VALIDITY"].error_message == "10 rows failed range check"
    assert rule_map["VALIDITY"].rule_config_hash is not None

    assert queue.get_run_status(sample_run_spec.run_id) == RunStatus.SUCCEEDED


def test_lease_fencing_rejection_on_stale_generation(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify lease fencing blocks publication when worker generation is outdated."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"fence-test-{uuid4()}")
    leased_gen1 = queue.claim_next_run(worker_id="worker-1")
    assert leased_gen1 is not None

    # Simulate expired lease and re-claim by worker-2
    with db_conn.transaction(), db_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluation_runs
            SET lease_expires_at = now() - interval '10 seconds'
            WHERE run_id = %s;
            """,
            (sample_run_spec.run_id,),
        )

    leased_gen2 = queue.claim_next_run(worker_id="worker-2")
    assert leased_gen2 is not None
    assert leased_gen2.lease_generation == leased_gen1.lease_generation + 1

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, rule_results = _build_test_assessment(
        sample_run_spec.tenant_id,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )

    # Zombie worker-1 attempts publication with stale generation
    with pytest.raises(PermissionError, match="Lease fencing error"):
        store.save_assessment_atomic(
            assessment=assessment,
            rule_results=rule_results,
            lease_generation=leased_gen1.lease_generation,
        )


def test_atomic_rollback_on_failure(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify entire transaction rolls back if any publication constraint fails."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"rollback-test-{uuid4()}")
    leased = queue.claim_next_run(worker_id="worker-rollback")
    assert leased is not None

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, _rule_results = _build_test_assessment(
        sample_run_spec.tenant_id,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )

    # Inject violated check constraint: total_observed != passed + failed + ...
    invalid_result = QualityRuleResult(
        rule_id=str(rule_ids[0]),
        dimension="COMPLETENESS",
        measurement_status=MeasurementStatus.MEASURED,
        counts=RuleCounts(
            passed=50,
            failed=10,
            missing=0,
            miscast=0,
            not_applicable=0,
            total_observed=999,
        ),
        computed_score=50.0,
    )

    with pytest.raises(psycopg.Error):
        store.save_assessment_atomic(
            assessment=assessment,
            rule_results=[invalid_result],
            lease_generation=leased.lease_generation,
        )

    # Ensure assessment was not saved and run was NOT marked SUCCEEDED
    assert store.get_assessment(assessment.assessment_id) is None
    assert queue.get_run_status(sample_run_spec.run_id) == RunStatus.LEASED


def test_worm_triggers_reject_updates_and_deletes(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify PostgreSQL WORM triggers reject UPDATE and DELETE on immutable tables."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"worm-test-{uuid4()}")
    leased = queue.claim_next_run(worker_id="worker-worm")
    assert leased is not None

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, rule_results = _build_test_assessment(
        sample_run_spec.tenant_id,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )
    store.save_assessment_atomic(assessment, rule_results, leased.lease_generation)
    set_tenant_context(db_conn, sample_run_spec.tenant_id)

    # 1. Reject UPDATE on assessments
    with (
        pytest.raises(RaiseException, match="strictly immutable"),
        db_conn.transaction(),
        db_conn.cursor() as cur,
    ):
        cur.execute(
            "UPDATE assessments SET dq_score = 99.9 WHERE assessment_id = %s;",
            (assessment.assessment_id,),
        )

    # 2. Reject DELETE on assessments
    with (
        pytest.raises(RaiseException, match="strictly immutable"),
        db_conn.transaction(),
        db_conn.cursor() as cur,
    ):
        cur.execute(
            "DELETE FROM assessments WHERE assessment_id = %s;",
            (assessment.assessment_id,),
        )

    # 3. Reject UPDATE on dimension_results
    with (
        pytest.raises(RaiseException, match="strictly immutable"),
        db_conn.transaction(),
        db_conn.cursor() as cur,
    ):
        cur.execute(
            "UPDATE dimension_results SET dimension_score = 99.9 WHERE assessment_id = %s;",
            (assessment.assessment_id,),
        )

    # 4. Reject UPDATE on canonical_quality_results
    with (
        pytest.raises(RaiseException, match="published result is immutable"),
        db_conn.transaction(),
        db_conn.cursor() as cur,
    ):
        cur.execute(
            "UPDATE canonical_quality_results SET computed_score = 99.9 WHERE run_id = %s;",
            (sample_run_spec.run_id,),
        )

    # 5. Reject DELETE on dataset_snapshots
    with (
        pytest.raises(RaiseException, match="snapshots are strictly append-only"),
        db_conn.transaction(),
        db_conn.cursor() as cur,
    ):
        cur.execute(
            "DELETE FROM dataset_snapshots WHERE snapshot_id = %s;",
            (sample_run_spec.snapshot.snapshot_id,),
        )

    # 6. Verify assessment is still intact and unchanged (DELETE was rejected)
    current = store.get_assessment(assessment.assessment_id)
    assert current is not None
    assert current.dq_score == pytest.approx(92.5)


def test_save_assessment_rejects_expired_lease_without_reclaim(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify worker cannot publish assessment if lease expired, even before re-claim."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"exp-lease-{uuid4()}")
    leased = queue.claim_next_run(worker_id="worker-expired-save")
    assert leased is not None

    # Simulate expired lease without another worker claiming it
    with db_conn.transaction(), db_conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluation_runs SET lease_expires_at = now() - interval '10 seconds' WHERE run_id = %s;",
            (sample_run_spec.run_id,),
        )

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, rule_results = _build_test_assessment(
        sample_run_spec.tenant_id,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )

    with pytest.raises(PermissionError, match="Lease fencing error"):
        store.save_assessment_atomic(
            assessment=assessment,
            rule_results=rule_results,
            lease_generation=leased.lease_generation,
        )


def test_atomic_persistence_with_outlier_advisory_signals(
    pg_dsn: str, sample_run_spec: RunSpec, db_conn: psycopg.Connection
) -> None:
    """Verify assessment with rule results AND IQR outlier advisory signals is atomically saved."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"outlier-test-{uuid4()}")
    leased = queue.claim_next_run(worker_id="worker-outlier-1")
    assert leased is not None

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, rule_results = _build_test_assessment(
        sample_run_spec.tenant_id,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )

    # Add IQR Outlier Advisory signal
    outlier_inp = OutlierResultInput(
        column_name="fare",
        total_evaluated=100,
        iqr=15.5,
        outlier_count=7,
    )
    outlier_result = build_outlier_advisory_result(outlier_inp)
    all_results = rule_results + [outlier_result]

    store.save_assessment_atomic(
        assessment=assessment,
        rule_results=all_results,
        lease_generation=leased.lease_generation,
    )

    # 1. Retrieve assessment and rule results
    retrieved = store.get_assessment(assessment.assessment_id)
    assert retrieved is not None

    fetched_rules = store.get_rule_results(assessment.assessment_id)
    assert len(fetched_rules) == 3

    outlier_fetched = next(
        (r for r in fetched_rules if r.source_kind == "OUTLIER"), None
    )
    assert outlier_fetched is not None
    assert outlier_fetched.target_column == "fare"
    assert outlier_fetched.is_advisory is True
    assert outlier_fetched.violations_count == 7
    assert outlier_fetched.measurement_status == "MEASURED"

    # 2. Check canonical_quality_results in DB directly
    set_tenant_context(db_conn, sample_run_spec.tenant_id)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_kind, target_column, rule_id, is_advisory, failed_count
            FROM canonical_quality_results
            WHERE run_id = %s AND source_kind = 'OUTLIER';
            """,
            (sample_run_spec.run_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "OUTLIER"
        assert row[1] == "fare"
        assert row[2] is None  # rule_id is NULL for outlier signals
        assert row[3] is True
        assert row[4] == 7

        # 3. Check outbox event
        cur.execute(
            "SELECT count(*) FROM assessment_outbox WHERE tenant_id = %s AND status = 'PENDING';",
            (sample_run_spec.tenant_id,),
        )
        assert cur.fetchone()[0] == 1


def test_adapter_cross_tenant_isolation(pg_dsn: str, sample_run_spec: RunSpec) -> None:
    """Verify adapter prevents cross-tenant data leaks when tenant_id context is provided."""
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)

    tenant_a = sample_run_spec.tenant_id
    tenant_b = uuid4()

    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"iso-{uuid4()}")
    leased = queue.claim_next_run(worker_id="worker-iso")
    assert leased is not None

    rule_ids = [r.rule_id for r in sample_run_spec.rules]
    assessment, rule_results = _build_test_assessment(
        tenant_a,
        sample_run_spec.run_id,
        sample_run_spec.snapshot.snapshot_id,
        rule_ids=rule_ids,
    )
    store.save_assessment_atomic(assessment, rule_results, leased.lease_generation)

    # Tenant A access succeeds
    assert (
        store.get_assessment(assessment.assessment_id, tenant_id=tenant_a) is not None
    )
    assert (
        store.get_assessment_by_run(sample_run_spec.run_id, tenant_id=tenant_a)
        is not None
    )
    assert len(store.get_rule_results(assessment.assessment_id, tenant_id=tenant_a)) > 0
    assert (
        queue.get_run_status(sample_run_spec.run_id, tenant_id=tenant_a)
        == RunStatus.SUCCEEDED
    )

    # Tenant B access returns None / empty list
    assert store.get_assessment(assessment.assessment_id, tenant_id=tenant_b) is None
    assert (
        store.get_assessment_by_run(sample_run_spec.run_id, tenant_id=tenant_b) is None
    )
    assert store.get_rule_results(assessment.assessment_id, tenant_id=tenant_b) == []
    assert queue.get_run_status(sample_run_spec.run_id, tenant_id=tenant_b) is None
