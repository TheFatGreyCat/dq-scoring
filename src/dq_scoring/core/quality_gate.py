"""Pure domain logic for 6-tier Quality Gate evaluation (BR-010).

Precedence: ERROR > Critical FAIL > INSUFFICIENT_EVIDENCE > FAIL > WARN > PASS.
"""

from dq_scoring.core.models import (
    GateEvaluationInput,
    MeasurementStatus,
    QualityGateStatus,
    QualityRuleResult,
    ScoringPolicy,
)


def _has_required_technical_failure(rules: list[QualityRuleResult]) -> bool:
    """Check if any required rule experienced a technical execution failure."""
    return any(
        r.is_required
        and r.measurement_status == MeasurementStatus.FAILED_TO_MEASURE.value
        for r in rules
    )


def _is_critical_violated(rule: QualityRuleResult, policy: ScoringPolicy) -> bool:
    """Check critical rule violation via Zero-Tolerance or an acceptance threshold.

    The rule's own threshold wins; otherwise the policy-wide critical threshold applies;
    with neither, any violation fails (zero tolerance).
    """
    if not rule.is_critical or not rule.gate_enabled or rule.is_advisory:
        return False
    if rule.measurement_status != MeasurementStatus.MEASURED.value:
        return False
    if rule.confidence is not None and rule.confidence < policy.min_critical_confidence:
        return False
    threshold = (
        rule.acceptance_threshold
        if rule.acceptance_threshold is not None
        else policy.critical_acceptance_threshold
    )
    if threshold is not None:
        return rule.computed_score is not None and rule.computed_score < threshold
    return rule.violations_count > 0


def _has_unmeasured_required(rules: list[QualityRuleResult]) -> bool:
    """Check if any required rule could not be measured."""
    unmeasured_statuses = {
        MeasurementStatus.NOT_MEASURABLE.value,
        MeasurementStatus.INSUFFICIENT_DATA.value,
        MeasurementStatus.SKIPPED_BY_BUDGET.value,
    }
    return any(
        r.is_required and r.measurement_status in unmeasured_statuses for r in rules
    )


def _extract_measured_dimensions(rules: list[QualityRuleResult]) -> set[str]:
    """Extract dimensions having at least one valid measured primary rule in R_d^m."""
    return {
        r.dimension
        for r in rules
        if r.measurement_status == MeasurementStatus.MEASURED.value
        and r.score_enabled
        and not r.is_advisory
        and r.is_primary_scoring_rule
        and r.computed_score is not None
    }


def _is_evidence_insufficient(inp: GateEvaluationInput) -> bool:
    """Evaluate whether evidence is insufficient for score assertion."""
    if inp.coverage_ratio is None or inp.coverage_ratio < inp.policy.coverage_threshold:
        return True
    if inp.dq_score is None:
        return True
    if _has_unmeasured_required(inp.rule_results):
        return True
    measured_dims = _extract_measured_dimensions(inp.rule_results)
    return bool(inp.required_dimensions - measured_dims)


def evaluate_quality_gate(inp: GateEvaluationInput) -> QualityGateStatus:
    """Evaluate 6-tier Quality Gate outcome adhering strictly to BR-010 precedence."""
    # 1. Technical measurement failure on required rule
    if _has_required_technical_failure(inp.rule_results):
        return QualityGateStatus.ERROR

    # 2. Critical rule violation (Zero-Tolerance or custom acceptance threshold)
    if any(_is_critical_violated(r, inp.policy) for r in inp.rule_results):
        return QualityGateStatus.FAIL

    # 3. Insufficient evidence (low coverage, missing required measurement/dimension)
    if _is_evidence_insufficient(inp):
        return QualityGateStatus.INSUFFICIENT_EVIDENCE

    # 4. Score failure threshold
    if inp.dq_score < inp.policy.gate_fail_threshold:
        return QualityGateStatus.FAIL

    # 5. Score warning threshold
    if inp.dq_score < inp.policy.gate_warn_threshold:
        return QualityGateStatus.WARN

    # 6. Quality pass
    return QualityGateStatus.PASS
