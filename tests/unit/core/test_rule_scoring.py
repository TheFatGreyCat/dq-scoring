"""Unit tests for Rule Score computation and partition verification."""

import pytest

from dq_scoring.core.models import MeasurementStatus, RuleCounts
from dq_scoring.core.rule_scoring import (
    RuleScoringInput,
    compute_rule_score,
    verify_partition_identity,
)


def test_partition_identity_valid():
    """Verify sum of mutually exclusive counts matches total_observed."""
    counts = RuleCounts(
        passed=80,
        failed=10,
        missing=5,
        miscast=5,
        not_applicable=0,
        total_observed=100,
    )
    assert verify_partition_identity(counts) is True


def test_partition_identity_invalid():
    """Detect broken partition count identity."""
    counts = RuleCounts(
        passed=80,
        failed=10,
        missing=5,
        miscast=0,
        not_applicable=0,
        total_observed=100,
    )
    assert verify_partition_identity(counts) is False


def test_compute_rule_score_null_policy_fail():
    """With null_policy='fail', missing is included in denominator."""
    counts = RuleCounts(
        passed=90,
        failed=5,
        missing=5,
        miscast=0,
        not_applicable=0,
        total_observed=100,
    )
    inp = RuleScoringInput(
        counts=counts,
        null_policy="fail",
        zero_denominator_status=MeasurementStatus.NOT_APPLICABLE.value,
    )
    status, score = compute_rule_score(inp)
    assert status == MeasurementStatus.MEASURED.value
    assert score == pytest.approx(90.0)


def test_compute_rule_score_null_policy_ignore():
    """With null_policy='ignore', missing is excluded from denominator."""
    counts = RuleCounts(
        passed=90,
        failed=10,
        missing=100,
        miscast=0,
        not_applicable=0,
        total_observed=200,
    )
    inp = RuleScoringInput(
        counts=counts,
        null_policy="ignore",
        zero_denominator_status=MeasurementStatus.NOT_APPLICABLE.value,
    )
    status, score = compute_rule_score(inp)
    assert status == MeasurementStatus.MEASURED.value
    assert score == pytest.approx(90.0)


def test_compute_rule_score_zero_denominator_not_applicable():
    """Zero denominator returns caller-specified NOT_APPLICABLE without setting score to 0 or 100."""
    counts = RuleCounts(total_observed=0)
    inp = RuleScoringInput(
        counts=counts,
        zero_denominator_status=MeasurementStatus.NOT_APPLICABLE.value,
    )
    status, score = compute_rule_score(inp)
    assert status == MeasurementStatus.NOT_APPLICABLE.value
    assert score is None


def test_compute_rule_score_zero_denominator_not_measurable():
    """Zero denominator returns caller-specified NOT_MEASURABLE when data is missing."""
    counts = RuleCounts(total_observed=0)
    inp = RuleScoringInput(
        counts=counts,
        zero_denominator_status=MeasurementStatus.NOT_MEASURABLE.value,
    )
    status, score = compute_rule_score(inp)
    assert status == MeasurementStatus.NOT_MEASURABLE.value
    assert score is None


def test_compute_rule_score_not_applicable_guard():
    """Guard clause returns NOT_APPLICABLE when rule is not applicable to schema."""
    counts = RuleCounts(passed=10, total_observed=10)
    inp = RuleScoringInput(
        counts=counts,
        zero_denominator_status=MeasurementStatus.NOT_APPLICABLE.value,
        is_applicable=False,
    )
    status, score = compute_rule_score(inp)
    assert status == MeasurementStatus.NOT_APPLICABLE.value
    assert score is None


def test_compute_rule_score_missing_metadata_guard():
    """Guard clause returns NOT_MEASURABLE when required reference metadata is missing."""
    counts = RuleCounts(passed=10, total_observed=10)
    inp = RuleScoringInput(
        counts=counts,
        zero_denominator_status=MeasurementStatus.NOT_MEASURABLE.value,
        has_required_metadata=False,
    )
    status, score = compute_rule_score(inp)
    assert status == MeasurementStatus.NOT_MEASURABLE.value
    assert score is None


def test_compute_rule_score_unsupported_null_policy():
    """Raise ValueError when unknown null policy is passed."""
    counts = RuleCounts(passed=10, total_observed=10)
    inp = RuleScoringInput(
        counts=counts,
        null_policy="invalid_policy",
        zero_denominator_status=MeasurementStatus.NOT_APPLICABLE.value,
    )
    with pytest.raises(ValueError, match="Unsupported null policy"):
        compute_rule_score(inp)
