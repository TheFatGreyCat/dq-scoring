"""Integration tests for evidence bounding and PII redaction at the persistence layer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import ImmutableAssessment, RunSpec
from dq_scoring.core.models import (
    DimensionResult,
    MeasurementStatus,
    PublicationStatus,
    QualityGateStatus,
    QualityRuleResult,
    RuleCounts,
)
from tests.support.run_seed import seed_run_prerequisites


def _setup_run(
    pg_dsn: str, sample_run_spec: RunSpec
) -> tuple[PostgresAssessmentStoreAdapter, PostgresQueueAdapter]:
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    sample_run_spec = seed_run_prerequisites(pg_dsn, sample_run_spec)
    queue.enqueue_run(sample_run_spec, idempotency_key=f"ev-run-{uuid4()}")
    leased = queue.claim_next_run(worker_id="ev-worker-1")
    assert leased is not None

    store = PostgresAssessmentStoreAdapter(dsn=pg_dsn)
    return store, queue


def test_save_assessment_redacts_pii_in_evidence(
    pg_dsn: str, sample_run_spec: RunSpec
) -> None:
    """Verify that sensitive PII in evidence samples and error message is redacted before write."""
    store, _queue = _setup_run(pg_dsn, sample_run_spec)

    rule_id = sample_run_spec.rules[0].rule_id
    raw_samples = [
        {
            "row_id": 1,
            "user_email": "john.doe@company.org",
            "phone_number": "(555) 234-5678",
            "tax_id": "123-45-6789",
        }
    ]
    rule_results = [
        QualityRuleResult(
            rule_id=str(rule_id),
            dimension="COMPLETENESS",
            measurement_status=MeasurementStatus.MEASURED,
            counts=RuleCounts(passed=99, failed=1, total_observed=100),
            computed_score=99.0,
            violations_count=1,
            evidence_samples=raw_samples,
            error_message="Failure observed for contact admin@secure.net",
        )
    ]
    dim_results = [
        DimensionResult(
            dimension="COMPLETENESS",
            dimension_score=99.0,
            coverage_ratio=1.0,
            rule_results=rule_results,
            dimension_weight=1.0,
        )
    ]
    assessment = ImmutableAssessment(
        assessment_id=uuid4(),
        tenant_id=sample_run_spec.tenant_id,
        run_id=sample_run_spec.run_id,
        snapshot_id=sample_run_spec.snapshot.snapshot_id,
        dq_score=99.0,
        publication_status=PublicationStatus.PUBLISHED,
        quality_gate=QualityGateStatus.PASS,
        coverage_ratio=1.0,
        dimension_results=dim_results,
        assessment_hash="test-evidence-hash-01",
        created_at=datetime.now(UTC),
    )

    store.save_assessment_atomic(
        assessment=assessment,
        rule_results=rule_results,
        lease_generation=1,
    )

    # Retrieve rule results through adapter
    results = store.get_rule_results(
        assessment_id=assessment.assessment_id,
        tenant_id=sample_run_spec.tenant_id,
    )
    assert len(results) == 1
    stored_r = results[0]

    # Verify PII was redacted
    samples = stored_r.evidence_samples
    assert samples is not None and len(samples) == 1
    sample_row = samples[0]
    assert "john.doe@company.org" not in str(sample_row)
    assert sample_row["user_email"] == "[REDACTED_EMAIL]"
    assert "(555) 234-5678" not in str(sample_row)
    assert sample_row["phone_number"] == "[REDACTED_PHONE]"
    assert "123-45-6789" not in str(sample_row)
    assert sample_row["tax_id"] == "[REDACTED_SSN]"

    # Verify error message was also redacted
    assert "admin@secure.net" not in str(stored_r.error_message)
    assert "[REDACTED_EMAIL]" in str(stored_r.error_message)


def test_save_assessment_caps_at_50_evidence_rows(
    pg_dsn: str, sample_run_spec: RunSpec
) -> None:
    """Verify that evidence samples exceeding 50 rows are truncated to 50 rows (DR-011)."""
    store, _queue = _setup_run(pg_dsn, sample_run_spec)

    rule_id = sample_run_spec.rules[0].rule_id
    raw_samples = [{"row_id": i, "val": -i} for i in range(85)]

    rule_results = [
        QualityRuleResult(
            rule_id=str(rule_id),
            dimension="COMPLETENESS",
            measurement_status=MeasurementStatus.MEASURED,
            counts=RuleCounts(passed=15, failed=85, total_observed=100),
            computed_score=15.0,
            violations_count=85,
            evidence_samples=raw_samples,
        )
    ]
    dim_results = [
        DimensionResult(
            dimension="COMPLETENESS",
            dimension_score=15.0,
            coverage_ratio=1.0,
            rule_results=rule_results,
            dimension_weight=1.0,
        )
    ]
    assessment = ImmutableAssessment(
        assessment_id=uuid4(),
        tenant_id=sample_run_spec.tenant_id,
        run_id=sample_run_spec.run_id,
        snapshot_id=sample_run_spec.snapshot.snapshot_id,
        dq_score=15.0,
        publication_status=PublicationStatus.PUBLISHED,
        quality_gate=QualityGateStatus.FAIL,
        coverage_ratio=1.0,
        dimension_results=dim_results,
        assessment_hash="test-evidence-hash-02",
        created_at=datetime.now(UTC),
    )

    store.save_assessment_atomic(
        assessment=assessment,
        rule_results=rule_results,
        lease_generation=1,
    )

    # Retrieve from DB and verify row count
    results = store.get_rule_results(
        assessment_id=assessment.assessment_id,
        tenant_id=sample_run_spec.tenant_id,
    )
    assert len(results) == 1
    assert len(results[0].evidence_samples or []) == 50



def test_save_assessment_enforces_assessment_evidence_byte_budget(
    pg_dsn: str, sample_run_spec: RunSpec
) -> None:
    """Verify that total evidence payload across all results does not exceed 500 KB (DR-011)."""
    from dq_scoring.core.entities import QualityRule

    rules = [
        QualityRule(
            rule_id=uuid4(),
            rule_code=f"R_BUDGET_{i}",
            dimension="completeness",
            rule_type="non_null",
            parameters={"column": "fare"},
            contribution_weight=1.0,
        )
        for i in range(12)
    ]
    spec = RunSpec(
        run_id=uuid4(),
        tenant_id=sample_run_spec.tenant_id,
        snapshot=sample_run_spec.snapshot,
        rules=rules,
        policy=sample_run_spec.policy,
    )
    store, _queue = _setup_run(pg_dsn, spec)

    # Create 12 rule results, each with large samples that would sum to > 600 KB without budgeting
    rule_results: list[QualityRuleResult] = []
    for r in spec.rules:
        # Each rule has 40 rows with 1.5 KB payload each ~= 60 KB per rule
        samples = [{"row_idx": j, "payload": "y" * 1500} for j in range(40)]
        rr = QualityRuleResult(
            rule_id=str(r.rule_id),
            dimension="COMPLETENESS",
            measurement_status=MeasurementStatus.MEASURED,
            counts=RuleCounts(passed=60, failed=40, total_observed=100),
            computed_score=60.0,
            violations_count=40,
            evidence_samples=samples,
        )
        rule_results.append(rr)

    dim_results = [
        DimensionResult(
            dimension="COMPLETENESS",
            dimension_score=60.0,
            coverage_ratio=1.0,
            rule_results=rule_results,
            dimension_weight=1.0,
        )
    ]

    assessment = ImmutableAssessment(
        assessment_id=uuid4(),
        tenant_id=spec.tenant_id,
        run_id=spec.run_id,
        snapshot_id=spec.snapshot.snapshot_id,
        dq_score=60.0,
        publication_status=PublicationStatus.PUBLISHED,
        quality_gate=QualityGateStatus.WARN,
        coverage_ratio=1.0,
        dimension_results=dim_results,
        assessment_hash="test-evidence-hash-03",
        created_at=datetime.now(UTC),
    )

    store.save_assessment_atomic(
        assessment=assessment,
        rule_results=rule_results,
        lease_generation=1,
    )

    # Query sum of pg_column_size(evidence_payload) directly from PostgreSQL
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        set_tenant_context(conn, spec.tenant_id)
        cur.execute(
            """
            SELECT coalesce(sum(pg_column_size(evidence_payload)), 0)
            FROM canonical_quality_results
            WHERE run_id = %s;
            """,
            (spec.run_id,),
        )
        total_stored_bytes = cur.fetchone()[0]

    # Total must strictly respect 500 KB limit and be non-zero
    assert 0 < total_stored_bytes <= 500 * 1024
    # Also verify through adapter retrieved objects that JSON UTF-8 payload <= 500 KB
    retrieved_results = store.get_rule_results(assessment_id=assessment.assessment_id, tenant_id=spec.tenant_id)
    import json
    app_evidence_bytes = sum(
        len(
            json.dumps(
                {k: v for k, v in [("samples", r.evidence_samples), ("error_message", r.error_message)] if v is not None},
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        )
        for r in retrieved_results
        if r.evidence_samples is not None or r.error_message is not None
    )
    assert 0 < app_evidence_bytes <= 500 * 1024


