"""Unit tests for PySparkComputeAdapter and SQL rule compiler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.core.entities import DatasetSnapshot, QualityRule
from dq_scoring.core.models import MeasurementStatus
from dq_scoring.core.rule_scoring import RuleScoringInput, compute_rule_score


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    """Module-scoped PySparkComputeAdapter fixture."""
    return PySparkComputeAdapter()


@pytest.fixture(scope="module")
def golden_snapshot(spark_adapter: PySparkComputeAdapter) -> DatasetSnapshot:
    from tests.support.object_snapshots import create_test_snapshot
    root = Path(__file__).resolve().parents[3]
    return create_test_snapshot(root / "tests/fixtures/chicago_taxi/chicago_taxi_golden_5k.csv")

def test_profile_snapshot(spark_adapter: PySparkComputeAdapter, golden_snapshot: DatasetSnapshot):
    """Verify single-pass snapshot profiling on selected columns."""
    metrics = spark_adapter.profile_snapshot(golden_snapshot, ["trip_id", "fare"])
    assert len(metrics) == 6
    metric_map = {(m.column_name, m.metric_name): m.metric_value for m in metrics}
    assert metric_map[("trip_id", "row_count")] == 5000
    assert metric_map[("trip_id", "null_count")] == 50
    assert metric_map[("fare", "row_count")] == 5000
    assert metric_map[("fare", "null_count")] == 100


def test_zero_denominator_empty_snapshot(spark_adapter: PySparkComputeAdapter):
    """Verify empty snapshot returns NOT_MEASURABLE for rules."""
    empty_snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="CSV",
        source_descriptor={"path": "/nonexistent.csv"},
        schema_definition={},
        total_rows=0,
        total_columns=0,
        captured_at=datetime.now(UTC),
    )
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="R1",
        dimension="Completeness",
        rule_type="NON_NULL",
        parameters={"column": "col_a"},
    )
    outputs = spark_adapter.execute_rules(empty_snapshot, [rule])
    assert len(outputs) == 1
    assert outputs[0].status == MeasurementStatus.NOT_MEASURABLE
    assert outputs[0].counts.total_observed == 0


def test_fault_containment_on_invalid_rule(spark_adapter: PySparkComputeAdapter, golden_snapshot: DatasetSnapshot):
    """Verify malformed rule records FAILED_TO_MEASURE while valid rules succeed."""
    valid_rule = QualityRule(
        rule_id=uuid4(),
        rule_code="VALID_01",
        dimension="Completeness",
        rule_type="NON_NULL",
        parameters={"column": "trip_id"},
    )
    malformed_rule = QualityRule(
        rule_id=uuid4(),
        rule_code="BAD_01",
        dimension="Consistency",
        rule_type="CROSS_FIELD",
        parameters={"column": "trip_id"},  # missing comparison_column
    )
    outputs = spark_adapter.execute_rules(golden_snapshot, [valid_rule, malformed_rule])
    out_map = {o.rule_id: o for o in outputs}
    assert out_map[valid_rule.rule_id].status == MeasurementStatus.MEASURED
    assert out_map[malformed_rule.rule_id].status == MeasurementStatus.FAILED_TO_MEASURE
    assert "missing comparison_column" in (out_map[malformed_rule.rule_id].error_message or "")


def test_bounded_evidence_samples(spark_adapter: PySparkComputeAdapter, golden_snapshot: DatasetSnapshot):
    """Verify failure evidence sampling is bounded by sample_limit."""
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="VAL_SAMPLE",
        dimension="Validity",
        rule_type="DOMAIN_RANGE",
        parameters={"column": "payment_type", "allowed_values": ["Cash"]},
    )
    outputs = spark_adapter.execute_rules(golden_snapshot, [rule], sample_limit=10)
    assert len(outputs) == 1
    assert len(outputs[0].evidence_samples) <= 10
    assert outputs[0].counts.failed > 10



def test_golden_5k_ground_truth_parity(spark_adapter: PySparkComputeAdapter, golden_snapshot: DatasetSnapshot):
    """Verify exact 100% count parity against golden_ground_truth_matrix.json for all 12 rules."""
    matrix_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tests"
        / "fixtures"
        / "chicago_taxi"
        / "golden_ground_truth_matrix.json"
    )
    with matrix_path.open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # Build 12 rule specifications
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

    rule_code_to_id = {}
    quality_rules = []
    for code, r_type, params in rules_def:
        gt_rule = next(r for r in ground_truth["rules"] if r["rule_code"] == code)
        r_id = uuid4()
        rule_code_to_id[code] = r_id
        quality_rules.append(
            QualityRule(
                rule_id=r_id,
                rule_code=code,
                dimension=gt_rule["dimension"],
                rule_type=r_type,
                parameters=params,
                is_required=gt_rule["is_required"],
                is_critical=gt_rule["is_critical"],
                is_advisory=gt_rule["is_advisory"],
                contribution_weight=gt_rule["contribution_weight"],
                null_policy=gt_rule["null_policy"],
            )
        )

    outputs = spark_adapter.execute_rules(golden_snapshot, quality_rules)
    out_map = {o.rule_id: o for o in outputs}

    for gt_rule in ground_truth["rules"]:
        code = gt_rule["rule_code"]
        r_id = rule_code_to_id[code]
        out = out_map[r_id]

        assert out.status == MeasurementStatus.MEASURED, f"Rule {code} status expected MEASURED, got {out.status}"
        assert out.counts.passed == gt_rule["counts"]["passed"], f"Rule {code} passed count mismatch: {out.counts.passed} != {gt_rule['counts']['passed']}"
        assert out.counts.failed == gt_rule["counts"]["failed"], f"Rule {code} failed count mismatch: {out.counts.failed} != {gt_rule['counts']['failed']}"
        assert out.counts.missing == gt_rule["counts"]["missing"], f"Rule {code} missing count mismatch: {out.counts.missing} != {gt_rule['counts']['missing']}"
        assert out.counts.miscast == gt_rule["counts"]["miscast"], f"Rule {code} miscast count mismatch: {out.counts.miscast} != {gt_rule['counts']['miscast']}"
        assert out.counts.not_applicable == gt_rule["counts"]["not_applicable"], f"Rule {code} na count mismatch: {out.counts.not_applicable} != {gt_rule['counts']['not_applicable']}"
        assert out.counts.total_observed == gt_rule["counts"]["total_observed"], f"Rule {code} total_observed mismatch"

        # Verify exact rule score calculation matches ground truth
        _status, calculated_score = compute_rule_score(
            RuleScoringInput(
                counts=out.counts,
                null_policy=gt_rule["null_policy"],
            )
        )
        assert calculated_score == pytest.approx(gt_rule["rule_score"], abs=1e-2), (
            f"Rule {code} score mismatch: {calculated_score} != {gt_rule['rule_score']}"
        )


def test_missing_dataset_file_raises_error(spark_adapter: PySparkComputeAdapter):
    """Verify infrastructure failure (non-existent file) raises exception instead of masking."""
    invalid_snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="local_csv",
        source_descriptor={"file_path": "non_existent_path_12345.csv"},
        schema_definition={},
        total_rows=100,
        total_columns=5,
        captured_at=datetime.now(UTC),
    )
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="TEST_01",
        dimension="Completeness",
        rule_type="NON_NULL",
        parameters={"column": "dummy"},
    )
    with pytest.raises(Exception):  # noqa: B017
        spark_adapter.execute_rules(invalid_snapshot, [rule])


def test_missing_column_marks_failed_to_measure(
    spark_adapter: PySparkComputeAdapter,
    golden_snapshot: DatasetSnapshot,
):
    """Verify rule targeting non-existent column produces FAILED_TO_MEASURE."""
    rule = QualityRule(
        rule_id=uuid4(),
        rule_code="NON_EXIST_COL",
        dimension="Completeness",
        rule_type="NON_NULL",
        parameters={"column": "column_that_does_not_exist"},
    )
    outputs = spark_adapter.execute_rules(golden_snapshot, [rule])
    assert len(outputs) == 1
    assert outputs[0].status == MeasurementStatus.FAILED_TO_MEASURE
    assert "not found in dataset" in (outputs[0].error_message or "")


def test_outlier_detection_iqr(spark_adapter: PySparkComputeAdapter, golden_snapshot: DatasetSnapshot):
    """Verify IQR outlier detection on fare column."""
    outlier_out = spark_adapter.detect_outliers(golden_snapshot, "fare", k=1.5, sample_limit=10)
    assert outlier_out.column_name == "fare"
    assert outlier_out.total_evaluated == 4860  # 5000 - 100 missing - 40 unparseable
    assert outlier_out.iqr > 0
    assert outlier_out.outlier_count >= 15
    assert len(outlier_out.outlier_samples) <= 10
