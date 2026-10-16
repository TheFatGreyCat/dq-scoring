"""Unit tests for 6-Tier Quality Gate evaluation logic (BR-010)."""

from dq_scoring.core.models import (
    GateEvaluationInput,
    MeasurementStatus,
    QualityGateStatus,
    QualityRuleResult,
    ScoringPolicy,
    StandardDimension,
)
from dq_scoring.core.quality_gate import evaluate_quality_gate


def test_quality_gate_precedence_tier_1_error():
    """Required rule with FAILED_TO_MEASURE triggers ERROR even if dq_score is high."""
    policy = ScoringPolicy()
    rule_err = QualityRuleResult(
        rule_id="r_req",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.FAILED_TO_MEASURE.value,
        is_required=True,
    )
    inp = GateEvaluationInput(
        rule_results=[rule_err],
        dq_score=95.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.ERROR


def test_quality_gate_precedence_error_over_critical_fail():
    """Tier 1 ERROR takes precedence over Tier 2 Critical FAIL."""
    policy = ScoringPolicy()
    rule_err = QualityRuleResult(
        rule_id="r_req",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.FAILED_TO_MEASURE.value,
        is_required=True,
    )
    rule_crit = QualityRuleResult(
        rule_id="r_crit",
        dimension=StandardDimension.COMPLETENESS.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        is_critical=True,
        violations_count=5,
    )
    inp = GateEvaluationInput(
        rule_results=[rule_err, rule_crit],
        dq_score=95.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.ERROR


def test_quality_gate_precedence_critical_fail_over_insufficient_evidence():
    """Tier 2 Critical FAIL takes precedence over Tier 3 INSUFFICIENT_EVIDENCE."""
    policy = ScoringPolicy()
    rule_crit = QualityRuleResult(
        rule_id="r_crit",
        dimension=StandardDimension.COMPLETENESS.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        is_critical=True,
        violations_count=1,
    )
    inp = GateEvaluationInput(
        rule_results=[rule_crit],
        dq_score=85.0,
        coverage_ratio=0.60,  # Below 0.80 threshold
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.FAIL


def test_quality_gate_tier_3_insufficient_evidence_low_coverage():
    """Coverage below policy threshold triggers INSUFFICIENT_EVIDENCE."""
    policy = ScoringPolicy()
    rule = QualityRuleResult(
        rule_id="r1",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=85.0,
    )
    inp = GateEvaluationInput(
        rule_results=[rule],
        dq_score=85.0,
        coverage_ratio=0.75,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.INSUFFICIENT_EVIDENCE


def test_quality_gate_tier_3_insufficient_evidence_unmeasured_required():
    """Required rule that is NOT_MEASURABLE triggers INSUFFICIENT_EVIDENCE."""
    policy = ScoringPolicy()
    rule_req = QualityRuleResult(
        rule_id="r_req",
        dimension=StandardDimension.VALIDITY.value,
        measurement_status=MeasurementStatus.NOT_MEASURABLE.value,
        is_required=True,
    )
    inp = GateEvaluationInput(
        rule_results=[rule_req],
        dq_score=85.0,
        coverage_ratio=0.85,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.INSUFFICIENT_EVIDENCE


def test_quality_gate_tier_4_fail_low_score():
    """DQ score below warn_min triggers FAIL."""
    policy = ScoringPolicy(warn_min=60.0, pass_min=80.0)
    rule = QualityRuleResult(
        rule_id="r1",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=55.0,
    )
    inp = GateEvaluationInput(
        rule_results=[rule],
        dq_score=55.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.FAIL


def test_quality_gate_tier_5_warn():
    """DQ score between warn_min and pass_min triggers WARN."""
    policy = ScoringPolicy(warn_min=60.0, pass_min=80.0)
    rule = QualityRuleResult(
        rule_id="r1",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=72.0,
    )
    inp = GateEvaluationInput(
        rule_results=[rule],
        dq_score=72.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.WARN


def test_quality_gate_tier_6_pass():
    """DQ score at or above pass_min triggers PASS."""
    policy = ScoringPolicy(warn_min=60.0, pass_min=80.0)
    rule = QualityRuleResult(
        rule_id="r1",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=MeasurementStatus.MEASURED.value,
        computed_score=92.5,
    )
    inp = GateEvaluationInput(
        rule_results=[rule],
        dq_score=92.5,
        coverage_ratio=0.90,
        policy=policy,
    )
    assert evaluate_quality_gate(inp) == QualityGateStatus.PASS
