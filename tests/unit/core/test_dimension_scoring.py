"""Unit tests for Dimension Score and Dimension Coverage aggregation."""

import pytest

from dq_scoring.core.dimension_scoring import (
    DimensionScoringInput,
    compute_dimension_result,
)
from dq_scoring.core.models import (
    MeasurementStatus,
    QualityRuleResult,
    StandardDimension,
)


def test_dimension_score_single_rule():
    """Single measured rule sets dimension score and 100% coverage."""
    rule = QualityRuleResult(
        rule_id="r1",
        dimension=StandardDimension.COMPLETENESS.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=95.0,
        contribution_weight=1.0,
    )
    inp = DimensionScoringInput(
        dimension=StandardDimension.COMPLETENESS.value,
        rules=[rule],
    )
    res = compute_dimension_result(inp)
    assert res.dimension_score == pytest.approx(95.0)
    assert res.coverage_ratio == pytest.approx(1.0)


def test_dimension_score_weighted_average():
    """Rules with different weights produce correct weighted average."""
    r1 = QualityRuleResult(
        rule_id="r1",
        dimension=StandardDimension.VALIDITY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=80.0,
        contribution_weight=1.0,
    )
    r2 = QualityRuleResult(
        rule_id="r2",
        dimension=StandardDimension.VALIDITY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=100.0,
        contribution_weight=3.0,
    )
    inp = DimensionScoringInput(
        dimension=StandardDimension.VALIDITY.value,
        rules=[r1, r2],
    )
    res = compute_dimension_result(inp)
    # (1*80 + 3*100) / 4 = 380 / 4 = 95.0
    assert res.dimension_score == pytest.approx(95.0)
    assert res.coverage_ratio == pytest.approx(1.0)


def test_dimension_conflict_group_secondary_rule_excluded():
    """Secondary rules in conflict group do not contribute to score or coverage."""
    r_primary = QualityRuleResult(
        rule_id="r_primary",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=90.0,
        conflict_group="dob_check",
        is_primary_scoring_rule=True,
        contribution_weight=1.0,
    )
    r_secondary = QualityRuleResult(
        rule_id="r_secondary",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=50.0,
        conflict_group="dob_check",
        is_primary_scoring_rule=False,
        contribution_weight=1.0,
    )
    inp = DimensionScoringInput(
        dimension=StandardDimension.ACCURACY.value,
        rules=[r_primary, r_secondary],
    )
    res = compute_dimension_result(inp)
    assert res.dimension_score == pytest.approx(90.0)
    assert res.coverage_ratio == pytest.approx(1.0)


def test_dimension_advisory_rule_excluded():
    """Advisory rules are excluded from score and coverage calculation."""
    r_normal = QualityRuleResult(
        rule_id="r_normal",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=92.0,
        contribution_weight=1.0,
    )
    r_advisory = QualityRuleResult(
        rule_id="r_adv",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        is_advisory=True,
        contribution_weight=0.0,
        computed_score=20.0,
    )
    inp = DimensionScoringInput(
        dimension=StandardDimension.ACCURACY.value,
        rules=[r_normal, r_advisory],
    )
    res = compute_dimension_result(inp)
    assert res.dimension_score == pytest.approx(92.0)
    assert res.coverage_ratio == pytest.approx(1.0)


def test_dimension_coverage_not_applicable_vs_not_measurable():
    """NOT_APPLICABLE rule is excluded from coverage denominator; NOT_MEASURABLE reduces coverage."""
    r_measured = QualityRuleResult(
        rule_id="r_m",
        dimension=StandardDimension.CONSISTENCY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=100.0,
        contribution_weight=1.0,
    )
    r_na = QualityRuleResult(
        rule_id="r_na",
        dimension=StandardDimension.CONSISTENCY.value,
        measurement_status=MeasurementStatus.NOT_APPLICABLE.value,
        contribution_weight=1.0,
    )
    r_nm = QualityRuleResult(
        rule_id="r_nm",
        dimension=StandardDimension.CONSISTENCY.value,
        measurement_status=MeasurementStatus.NOT_MEASURABLE.value,
        contribution_weight=1.0,
    )
    # Expected: r_m (w=1) + r_nm (w=1) -> denominator = 2. r_na excluded.
    # Measured: r_m (w=1) -> numerator = 1. Coverage = 1/2 = 0.5.
    inp = DimensionScoringInput(
        dimension=StandardDimension.CONSISTENCY.value,
        rules=[r_measured, r_na, r_nm],
    )
    res = compute_dimension_result(inp)
    assert res.dimension_score == pytest.approx(100.0)
    assert res.coverage_ratio == pytest.approx(0.5)


def test_dimension_empty_rules():
    """When no measured rules exist, dimension score is None (never forced to 0)."""
    r_nm = QualityRuleResult(
        rule_id="r_nm",
        dimension=StandardDimension.TIMELINESS.value,
        measurement_status=MeasurementStatus.NOT_MEASURABLE.value,
        contribution_weight=1.0,
    )
    inp = DimensionScoringInput(
        dimension=StandardDimension.TIMELINESS.value,
        rules=[r_nm],
    )
    res = compute_dimension_result(inp)
    assert res.dimension_score is None
    assert res.coverage_ratio == pytest.approx(0.0)
