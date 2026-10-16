"""Golden Matrix Unit Tests G1–G9 for Quality Gate & Publication Invariants.

Specification reference: IMPLEMENTATION_REUSE_GUIDE.md Section 5.5.
"""

from dq_scoring.core.models import (
    GateEvaluationInput,
    MeasurementStatus,
    PublicationCheckInput,
    PublicationStatus,
    QualityGateStatus,
    ScoringPolicy,
)
from dq_scoring.core.outlier_advisory import (
    OutlierResultInput,
    build_outlier_advisory_result,
)
from dq_scoring.core.publication import determine_publication_status
from dq_scoring.core.quality_gate import evaluate_quality_gate


def test_g1_required_rule_technical_failure(make_rule):
    """G1: 1 required rule FAILED_TO_MEASURE -> Gate ERROR, Publication WITHHELD, dq_score null."""
    policy = ScoringPolicy()
    r_err = make_rule(
        "r1",
        status=MeasurementStatus.FAILED_TO_MEASURE.value,
        is_required=True,
        score=None,
    )
    r_ok = make_rule("r2", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_err, r_ok], dq_score=85.0, coverage_ratio=0.90, policy=policy
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


def test_g2_critical_violation_sufficient_evidence(make_rule):
    """G2: Critical violation + sufficient evidence -> Gate FAIL, Publication PUBLISHED, dq_score 85.0."""
    policy = ScoringPolicy()
    r_crit = make_rule("r1", is_critical=True, violations=1, score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_crit], dq_score=85.0, coverage_ratio=0.90, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.FAIL

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 85.0


def test_g3_critical_violation_insufficient_evidence(make_rule):
    """G3: Critical violation + insufficient evidence -> Gate FAIL, Publication WITHHELD, dq_score null."""
    policy = ScoringPolicy()
    r_crit = make_rule("r1", is_critical=True, violations=1, score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_crit], dq_score=85.0, coverage_ratio=0.60, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.FAIL

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.60,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g4_low_coverage_insufficient_evidence(make_rule):
    """G4: Coverage < 80% (75%) -> Gate INSUFFICIENT_EVIDENCE, Publication WITHHELD, dq_score null."""
    policy = ScoringPolicy()
    r = make_rule("r1", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r], dq_score=85.0, coverage_ratio=0.75, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.75,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g5_unmeasured_required_rule(make_rule):
    """G5: 1 required rule NOT_MEASURABLE -> Gate INSUFFICIENT_EVIDENCE, Publication WITHHELD, dq_score null."""
    policy = ScoringPolicy()
    r_req = make_rule(
        "r1",
        status=MeasurementStatus.NOT_MEASURABLE.value,
        is_required=True,
        score=None,
    )
    r_ok = make_rule("r2", score=85.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r_req, r_ok], dq_score=85.0, coverage_ratio=0.85, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.INSUFFICIENT_EVIDENCE

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=85.0,
        coverage_ratio=0.85,
        policy=policy,
        has_unmeasured_required_rules=True,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.WITHHELD
    assert pub_score is None


def test_g6_low_score_fail(make_rule):
    """G6: Score < 60 (55.0) -> Gate FAIL, Publication PUBLISHED, dq_score 55.0."""
    policy = ScoringPolicy()
    r = make_rule("r1", score=55.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r], dq_score=55.0, coverage_ratio=0.90, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.FAIL

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=55.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 55.0


def test_g7_warning_score_warn(make_rule):
    """G7: Score in [60, 80) (72.0) -> Gate WARN, Publication PUBLISHED, dq_score 72.0."""
    policy = ScoringPolicy()
    r = make_rule("r1", score=72.0)

    gate_inp = GateEvaluationInput(
        rule_results=[r], dq_score=72.0, coverage_ratio=0.90, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.WARN

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=72.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 72.0


def test_g8_quality_pass(make_rule):
    """G8: Score >= 80 (92.5) -> Gate PASS, Publication PUBLISHED, dq_score 92.5."""
    policy = ScoringPolicy()
    r = make_rule("r1", score=92.5)

    gate_inp = GateEvaluationInput(
        rule_results=[r], dq_score=92.5, coverage_ratio=0.90, policy=policy
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.PASS

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=92.5,
        coverage_ratio=0.90,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 92.5


def test_g9_outlier_advisory_isolation(make_rule):
    """G9: IQR Outlier advisory has weight 0.0 -> Gate PASS, Publication PUBLISHED, dq_score 92.5."""
    policy = ScoringPolicy()
    r_core = make_rule("r1", score=92.5)
    r_outlier = build_outlier_advisory_result(
        OutlierResultInput(
            column_name="amt", total_evaluated=100, iqr=15.0, outlier_count=5
        )
    )

    gate_inp = GateEvaluationInput(
        rule_results=[r_core, r_outlier],
        dq_score=92.5,
        coverage_ratio=0.90,
        policy=policy,
    )
    gate_status = evaluate_quality_gate(gate_inp)
    assert gate_status == QualityGateStatus.PASS

    pub_inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=gate_status,
        dq_score=92.5,
        coverage_ratio=0.90,
        policy=policy,
    )
    pub_status, pub_score = determine_publication_status(pub_inp)
    assert pub_status == PublicationStatus.PUBLISHED
    assert pub_score == 92.5
