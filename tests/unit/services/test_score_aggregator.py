"""Unit tests for ScoreAggregator."""

from dq_scoring.core.models import (
    PublicationStatus,
    QualityGateStatus,
    ScoringPolicy,
    StandardDimension,
)
from dq_scoring.services.score_aggregator import ScoreAggregator


def test_score_aggregator_publish_pass(make_rule):
    aggregator = ScoreAggregator()
    policy = ScoringPolicy()
    r1 = make_rule("r1", dimension=StandardDimension.COMPLETENESS.value, score=90.0)
    r2 = make_rule("r2", dimension=StandardDimension.ACCURACY.value, score=85.0)

    summary = aggregator.aggregate(
        rule_results=[r1, r2],
        policy=policy,
        required_dimensions={StandardDimension.COMPLETENESS.value},
    )

    assert summary.dq_score is not None
    assert summary.quality_gate == QualityGateStatus.PASS
    assert summary.publication_status == PublicationStatus.PUBLISHED
    assert summary.published_score == summary.dq_score
    assert len(summary.dimension_results) == 2
    assert summary.all_required_dimensions_measured is True


def test_score_aggregator_withheld_missing_required_dimension(make_rule):
    aggregator = ScoreAggregator()
    policy = ScoringPolicy()
    r1 = make_rule("r1", dimension=StandardDimension.COMPLETENESS.value, score=90.0)

    summary = aggregator.aggregate(
        rule_results=[r1],
        policy=policy,
        required_dimensions={
            StandardDimension.COMPLETENESS.value,
            StandardDimension.ACCURACY.value,
        },
    )

    assert summary.all_required_dimensions_measured is False
    assert summary.quality_gate == QualityGateStatus.INSUFFICIENT_EVIDENCE
    assert summary.publication_status == PublicationStatus.WITHHELD
    assert summary.published_score is None
