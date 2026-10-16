"""Golden Matrix Unit Tests G10–G19 for Quality Gate & Publication Invariants.

Specification reference: IMPLEMENTATION_REUSE_GUIDE.md Section 5.5.
"""

from dq_scoring.core.models import (
    GateEvaluationInput,
    MeasurementStatus,
    PublicationCheckInput,
    PublicationStatus,
    QualityGateStatus,
    ScoringPolicy,
    StandardDimension,
)
from dq_scoring.core.publication import determine_publication_status
from dq_scoring.core.quality_gate import evaluate_quality_gate


def test_g10_zero_denominator_predicate_not_applicable(make_rule):
    """G10: Valid predicate filters 0 rows -> Rule is NOT_APPLICABLE (excluded from coverage denominator)."""
    policy = ScoringPolicy()
    r_na = make_rule("r_na", status=MeasurementStatus.NOT_APPLICABLE.value, score=None)
    r_ok = make_rule("r_ok", score=90.0)

    # 1 rule measured, 1 rule NOT_APPLICABLE -> coverage is 1/1 = 1.0 (>= 0.80)
    gate_inp = GateEvaluationInput(
        rule_results=[r_na, r_ok], dq_score=90.0, coverage_ratio=1.0, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.PASS

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=90.0,
        coverage_ratio=1.0,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 90.0


def test_g11_zero_denominator_empty_not_measurable(make_rule):
    """G11: Missing ref/empty table -> Rule is NOT_MEASURABLE (included in coverage denominator, degrades coverage)."""
    policy = ScoringPolicy()
    r_nm = make_rule("r_nm", status=MeasurementStatus.NOT_MEASURABLE.value, score=None)
    r_ok = make_rule("r_ok", score=90.0)

    # 1 measured / 2 applicable = 0.50 (< 0.80) -> INSUFFICIENT_EVIDENCE
    gate_inp = GateEvaluationInput(
        rule_results=[r_nm, r_ok], dq_score=90.0, coverage_ratio=0.50, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=90.0,
        coverage_ratio=0.50,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g12_required_gate_only_unmeasured(make_rule):
    """G12: Required Gate-only rule unmeasured -> Gate INSUFFICIENT_EVIDENCE, Publication WITHHELD."""
    policy = ScoringPolicy()
    r_go = make_rule(
        "r_go",
        status=MeasurementStatus.NOT_MEASURABLE.value,
        is_required=True,
        score_enabled=False,
        gate_enabled=True,
        score=None,
    )
    r_ok = make_rule("r_ok", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_go, r_ok], dq_score=85.0, coverage_ratio=0.90, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.90,
        policy=policy,
        has_unmeasured_required_rules=True,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g13_optional_critical_unmeasured(make_rule):
    """G13: Optional Critical rule unmeasured -> Gate PASS (if other rules pass), Publication PUBLISHED."""
    policy = ScoringPolicy()
    r_opt_crit = make_rule(
        "r_crit",
        status=MeasurementStatus.NOT_MEASURABLE.value,
        is_required=False,
        is_critical=True,
        score=None,
    )
    r_ok = make_rule("r1", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_opt_crit, r_ok],
        dq_score=85.0,
        coverage_ratio=0.82,
        policy=policy,
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.PASS

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.82,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 85.0


def test_g14_all_dimensions_out_of_scope(make_rule):
    """G14: All rules NOT_APPLICABLE -> dq_score is None, Gate INSUFFICIENT_EVIDENCE, Publication WITHHELD."""
    policy = ScoringPolicy()
    r_na = make_rule("r1", status=MeasurementStatus.NOT_APPLICABLE.value, score=None)

    gate_inp = GateEvaluationInput(
        rule_results=[r_na], dq_score=None, coverage_ratio=None, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=None,
        coverage_ratio=None,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g15_optional_rule_technical_failure(make_rule):
    """G15: Optional rule FAILED_TO_MEASURE -> Gate PASS (not ERROR), Publication PUBLISHED."""
    policy = ScoringPolicy()
    r_opt_fail = make_rule(
        "r_opt",
        status=MeasurementStatus.FAILED_TO_MEASURE.value,
        is_required=False,
        score=None,
    )
    r_ok = make_rule("r1", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_opt_fail, r_ok],
        dq_score=85.0,
        coverage_ratio=0.82,
        policy=policy,
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.PASS

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.82,
        policy=policy,
        has_failed_required_rules=False,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 85.0


def test_g16_custom_policy_publication_threshold(make_rule):
    """G16: Custom publication_threshold=0.85, coverage=0.82 -> Gate INSUFFICIENT_EVIDENCE, Publication WITHHELD."""
    policy = ScoringPolicy(publication_threshold=0.85)
    r = make_rule("r1", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r], dq_score=85.0, coverage_ratio=0.82, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.82,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g17_required_dimension_only_secondary_rule(make_rule):
    """G17: Required dimension only has secondary rules -> Gate INSUFFICIENT_EVIDENCE, Publication WITHHELD."""
    policy = ScoringPolicy()
    r_sec = make_rule(
        "r_sec",
        dimension=StandardDimension.ACCURACY.value,
        is_primary=False,
        score=85.0,
    )

    gate_inp = GateEvaluationInput(
        rule_results=[r_sec],
        dq_score=85.0,
        coverage_ratio=0.85,
        policy=policy,
        required_dimensions={StandardDimension.ACCURACY.value},
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.85,
        policy=policy,
        all_required_dimensions_measured=False,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g18_required_gate_only_technical_failure(make_rule):
    """G18: Required Gate-only rule FAILED_TO_MEASURE -> Gate ERROR, Publication WITHHELD."""
    policy = ScoringPolicy()
    r_go_err = make_rule(
        "r_go",
        status=MeasurementStatus.FAILED_TO_MEASURE.value,
        is_required=True,
        score_enabled=False,
        gate_enabled=True,
        score=None,
    )
    r_ok = make_rule("r_ok", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_go_err, r_ok], dq_score=85.0, coverage_ratio=0.90, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.ERROR

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.90,
        policy=policy,
        has_failed_required_rules=True,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g19_critical_violation_with_low_coverage(make_rule):
    """G19: Critical violation + low coverage (0.65) -> Gate FAIL (precedence over INSUFFICIENT_EVIDENCE), Publication WITHHELD."""
    policy = ScoringPolicy()
    r_crit = make_rule("r_crit", is_critical=True, violations=2, score=50.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_crit], dq_score=85.0, coverage_ratio=0.65, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.FAIL

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.65,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None
