"""Unit tests for ValidationService."""

from datetime import UTC, datetime
from uuid import uuid4

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.core.entities import (
    DatasetSnapshot,
    QualityRule,
    RuleExecutionOutput,
)
from dq_scoring.core.models import MeasurementStatus, RuleCounts
from dq_scoring.services.validation_service import ValidationService


def _sample_snapshot() -> DatasetSnapshot:
    return DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="parquet",
        source_descriptor={"path": "s3://bucket/test.parquet"},
        schema_definition={"id": "int", "amt": "float"},
        total_rows=100,
        total_columns=2,
        captured_at=datetime.now(UTC),
    )


def test_validation_service_success():
    compute = InMemoryComputeAdapter()
    service = ValidationService(compute)
    snapshot = _sample_snapshot()

    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R1",
        dimension="Completeness",
        rule_type="not_null",
    )
    compute.set_rule_output(
        rule.rule_id,
        RuleExecutionOutput(
            rule_id=rule.rule_id,
            counts=RuleCounts(
                passed=95,
                failed=5,
                missing=0,
                miscast=0,
                not_applicable=0,
                total_observed=100,
            ),
        ),
    )

    results = service.validate_ruleset(snapshot, [rule])
    assert len(results) == 1
    res = results[0]
    assert res.computed_score == 95.0
    assert res.violations_count == 5
    assert res.measurement_status == MeasurementStatus.MEASURED.value


def test_validation_service_technical_failure():
    compute = InMemoryComputeAdapter()
    service = ValidationService(compute)
    snapshot = _sample_snapshot()

    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R_ERR",
        dimension="Accuracy",
        rule_type="regex",
        is_required=True,
    )
    compute.set_rule_output(
        rule.rule_id,
        RuleExecutionOutput(
            rule_id=rule.rule_id,
            counts=RuleCounts(),
            status=MeasurementStatus.FAILED_TO_MEASURE,
            error_message="Invalid regex pattern syntax",
        ),
    )

    results = service.validate_ruleset(snapshot, [rule])
    assert len(results) == 1
    assert results[0].measurement_status == MeasurementStatus.FAILED_TO_MEASURE.value
    assert results[0].computed_score is None


def test_validation_service_not_applicable():
    compute = InMemoryComputeAdapter()
    service = ValidationService(compute)
    snapshot = _sample_snapshot()

    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R_NA",
        dimension="Validity",
        rule_type="range",
    )
    compute.set_rule_output(
        rule.rule_id,
        RuleExecutionOutput(
            rule_id=rule.rule_id,
            counts=RuleCounts(),
            status=MeasurementStatus.NOT_APPLICABLE,
        ),
    )

    results = service.validate_ruleset(snapshot, [rule])
    assert len(results) == 1
    assert results[0].measurement_status == MeasurementStatus.NOT_APPLICABLE.value
    assert results[0].computed_score is None


def test_validation_service_partition_identity_violation():
    compute = InMemoryComputeAdapter()
    service = ValidationService(compute)
    snapshot = _sample_snapshot()

    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R_PART_FAIL",
        dimension="Completeness",
        rule_type="not_null",
    )
    # Mutually exclusive sum: 50 + 10 + 5 + 5 + 0 = 70 != total_observed (100)
    compute.set_rule_output(
        rule.rule_id,
        RuleExecutionOutput(
            rule_id=rule.rule_id,
            counts=RuleCounts(
                passed=50,
                failed=10,
                missing=5,
                miscast=5,
                not_applicable=0,
                total_observed=100,
            ),
        ),
    )

    results = service.validate_ruleset(snapshot, [rule])
    assert len(results) == 1
    res = results[0]
    assert res.measurement_status == MeasurementStatus.FAILED_TO_MEASURE.value
    assert res.computed_score is None
    assert res.counts is not None
    assert res.counts.total_observed == 100
    assert res.error_message is not None
    assert "Partition identity" in res.error_message
