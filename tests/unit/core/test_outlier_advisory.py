"""Unit tests for IQR Outlier Advisory signal normalization (FR-DET-003..005)."""

from dq_scoring.core.models import (
    MeasurementStatus,
    StandardDimension,
)
from dq_scoring.core.outlier_advisory import (
    OutlierResultInput,
    build_outlier_advisory_result,
)


def test_outlier_advisory_valid_sample():
    """Valid statistical distribution produces MEASURED advisory result with zero weight."""
    inp = OutlierResultInput(
        column_name="amount",
        total_evaluated=100,
        iqr=15.5,
        outlier_count=3,
        is_all_null=False,
    )
    res = build_outlier_advisory_result(inp)
    assert res.rule_id == "outlier_iqr_amount"
    assert res.dimension == StandardDimension.ACCURACY.value
    assert res.measurement_status == MeasurementStatus.MEASURED.value
    assert res.is_advisory is True
    assert res.contribution_weight == 0.0
    assert res.score_enabled is False
    assert res.gate_enabled is False
    assert res.computed_score is None
    assert res.violations_count == 3


def test_outlier_advisory_insufficient_sample():
    """Sample size < 4 produces NOT_MEASURABLE advisory result."""
    inp = OutlierResultInput(
        column_name="amount",
        total_evaluated=3,
        iqr=10.0,
        outlier_count=0,
        is_all_null=False,
    )
    res = build_outlier_advisory_result(inp)
    assert res.measurement_status == MeasurementStatus.NOT_MEASURABLE.value


def test_outlier_advisory_zero_iqr():
    """Zero IQR (constant value) produces NOT_MEASURABLE advisory result."""
    inp = OutlierResultInput(
        column_name="amount",
        total_evaluated=50,
        iqr=0.0,
        outlier_count=0,
        is_all_null=False,
    )
    res = build_outlier_advisory_result(inp)
    assert res.measurement_status == MeasurementStatus.NOT_MEASURABLE.value


def test_outlier_advisory_all_null():
    """All null column produces NOT_MEASURABLE advisory result."""
    inp = OutlierResultInput(
        column_name="amount",
        total_evaluated=50,
        iqr=12.0,
        outlier_count=0,
        is_all_null=True,
    )
    res = build_outlier_advisory_result(inp)
    assert res.measurement_status == MeasurementStatus.NOT_MEASURABLE.value
