"""Regression tests for the ScoringPolicy contract (unknown fields, threshold order, critical fallback)."""

import pytest
from pydantic import ValidationError

from dq_scoring.core.models import (
    GateEvaluationInput,
    MeasurementStatus,
    QualityGateStatus,
    QualityRuleResult,
    ScoringPolicy,
)
from dq_scoring.core.quality_gate import evaluate_quality_gate


def test_scoring_policy_rejects_unknown_fields() -> None:
    """Misspelled fields must fail loudly instead of silently falling back to defaults."""
    with pytest.raises(ValidationError):
        ScoringPolicy(gate_fail_threshold=10.0)


def test_scoring_policy_rejects_fail_threshold_above_warn_threshold() -> None:
    with pytest.raises(ValidationError):
        ScoringPolicy(warn_min=90.0, pass_min=80.0)


def _critical_rule(score: float, violations: int) -> QualityRuleResult:
    return QualityRuleResult(
        rule_id="r1",
        dimension="VALIDITY",
        measurement_status=MeasurementStatus.MEASURED.value,
        is_critical=True,
        computed_score=score,
        violations_count=violations,
    )


def test_policy_critical_acceptance_threshold_applies_when_rule_has_none() -> None:
    """A critical rule scoring 97 with 3 violations passes a policy-level threshold of 95."""
    policy = ScoringPolicy(critical_acceptance_threshold=95.0)
    gate = evaluate_quality_gate(
        GateEvaluationInput(
            rule_results=[_critical_rule(97.0, 3)],
            dq_score=97.0,
            coverage_ratio=1.0,
            policy=policy,
        )
    )
    assert gate == QualityGateStatus.PASS


def test_zero_tolerance_remains_default_without_any_threshold() -> None:
    gate = evaluate_quality_gate(
        GateEvaluationInput(
            rule_results=[_critical_rule(97.0, 3)],
            dq_score=97.0,
            coverage_ratio=1.0,
            policy=ScoringPolicy(),
        )
    )
    assert gate == QualityGateStatus.FAIL
