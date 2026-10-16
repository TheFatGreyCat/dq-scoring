"""Unit tests for Assessment Publication determination logic (BR-012)."""

from dq_scoring.core.models import (
    PublicationCheckInput,
    PublicationStatus,
    QualityGateStatus,
    ScoringPolicy,
)
from dq_scoring.core.publication import determine_publication_status


def test_publication_eligible():
    """All criteria met publishes score."""
    policy = ScoringPolicy(publication_threshold=0.80)
    inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=QualityGateStatus.PASS,
        dq_score=92.5,
        coverage_ratio=0.90,
        policy=policy,
        all_required_dimensions_measured=True,
        has_failed_required_rules=False,
        has_unmeasured_required_rules=False,
    )
    status, score = determine_publication_status(inp)
    assert status == PublicationStatus.PUBLISHED
    assert score == 92.5


def test_publication_withheld_on_gate_error():
    """Gate ERROR forces publication status WITHHELD and dq_score None."""
    policy = ScoringPolicy()
    inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=QualityGateStatus.ERROR,
        dq_score=85.0,
        coverage_ratio=0.90,
        policy=policy,
    )
    status, score = determine_publication_status(inp)
    assert status == PublicationStatus.WITHHELD
    assert score is None


def test_publication_withheld_on_insufficient_evidence():
    """Gate INSUFFICIENT_EVIDENCE forces publication status WITHHELD and dq_score None."""
    policy = ScoringPolicy()
    inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=QualityGateStatus.INSUFFICIENT_EVIDENCE,
        dq_score=85.0,
        coverage_ratio=0.75,
        policy=policy,
    )
    status, score = determine_publication_status(inp)
    assert status == PublicationStatus.WITHHELD
    assert score is None


def test_publication_withheld_on_failed_run():
    """RunStatus FAILED prevents publication even if intermediate scores exist."""
    policy = ScoringPolicy()
    inp = PublicationCheckInput(
        run_status="FAILED",
        gate_status=QualityGateStatus.PASS,
        dq_score=95.0,
        coverage_ratio=0.95,
        policy=policy,
    )
    status, score = determine_publication_status(inp)
    assert status == PublicationStatus.WITHHELD
    assert score is None


def test_publication_withheld_when_critical_violated_under_low_coverage():
    """Gate FAIL under low coverage retains Gate FAIL but withholds publication score."""
    policy = ScoringPolicy(publication_threshold=0.80)
    inp = PublicationCheckInput(
        run_status="SUCCEEDED",
        gate_status=QualityGateStatus.FAIL,
        dq_score=85.0,
        coverage_ratio=0.60,
        policy=policy,
    )
    status, score = determine_publication_status(inp)
    assert status == PublicationStatus.WITHHELD
    assert score is None
