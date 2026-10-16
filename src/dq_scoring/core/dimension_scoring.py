"""Pure domain logic for Dimension Score and Dimension Coverage aggregation."""

from pydantic import BaseModel, ConfigDict

from dq_scoring.core.models import (
    DimensionResult,
    MeasurementStatus,
    QualityRuleResult,
)


class DimensionScoringInput(BaseModel):
    """Input payload for aggregating rules into a dimension score and coverage."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    rules: list[QualityRuleResult]
    dimension_weight: float = 1.0


def is_dimension_measured_rule(rule: QualityRuleResult) -> bool:
    """Check if rule qualifies for R_d^m (Theory §11)."""
    return (
        rule.measurement_status == MeasurementStatus.MEASURED.value
        and rule.score_enabled
        and not rule.is_advisory
        and rule.is_primary_scoring_rule
        and rule.computed_score is not None
        and rule.contribution_weight > 0
    )


def is_dimension_expected_rule(rule: QualityRuleResult) -> bool:
    """Check if rule qualifies for R_d^e (Theory §11.1).

    Rules that are truly NOT_APPLICABLE, ADVISORY or gate-only (score_enabled=False) are
    excluded from the coverage denominator: they can never enter R_d^m.
    """
    return (
        not rule.is_advisory
        and rule.score_enabled
        and rule.measurement_status != MeasurementStatus.NOT_APPLICABLE.value
        and rule.is_primary_scoring_rule
        and rule.contribution_weight > 0
    )


def required_dimensions(rules: list[QualityRuleResult]) -> set[str]:
    """Dimensions the ruleset expects to score: at least one rule in R_d^e."""
    return {r.dimension for r in rules if is_dimension_expected_rule(r)}


def compute_dimension_result(inp: DimensionScoringInput) -> DimensionResult:
    """Compute Dimension Score D_d and Dimension Coverage C_d per DQ_SCORING_THEORY §11."""
    measured_rules = [r for r in inp.rules if is_dimension_measured_rule(r)]
    expected_rules = [r for r in inp.rules if is_dimension_expected_rule(r)]

    sum_measured_weight = sum(r.contribution_weight for r in measured_rules)
    sum_expected_weight = sum(r.contribution_weight for r in expected_rules)

    dimension_score: float | None = None
    if sum_measured_weight > 0:
        weighted_score_sum = sum(
            r.contribution_weight * (r.computed_score or 0.0) for r in measured_rules
        )
        dimension_score = weighted_score_sum / sum_measured_weight

    coverage_ratio: float | None = None
    if sum_expected_weight > 0:
        coverage_ratio = sum_measured_weight / sum_expected_weight

    return DimensionResult(
        dimension=inp.dimension,
        dimension_score=dimension_score,
        coverage_ratio=coverage_ratio,
        rule_results=inp.rules,
        dimension_weight=inp.dimension_weight,
    )
