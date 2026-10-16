"""Pure domain logic for Rule Score calculation and partition verification."""

from pydantic import BaseModel, ConfigDict

from dq_scoring.core.models import MeasurementStatus, RuleCounts


class RuleScoringInput(BaseModel):
    """Input parameters for computing an individual rule score."""

    model_config = ConfigDict(frozen=True)

    counts: RuleCounts
    null_policy: str = "fail"
    zero_denominator_status: str = MeasurementStatus.NOT_MEASURABLE.value
    is_applicable: bool = True
    has_required_metadata: bool = True


def verify_partition_identity(counts: RuleCounts) -> bool:
    """Verify DDIA partition invariant: sum of mutually exclusive counts == total_observed."""
    partition_sum = (
        counts.passed
        + counts.failed
        + counts.missing
        + counts.miscast
        + counts.not_applicable
    )
    return partition_sum == counts.total_observed


def _calculate_denominator(counts: RuleCounts, null_policy: str) -> int:
    """Calculate effective denominator n_r based on configured null policy."""
    if null_policy == "fail":
        return counts.passed + counts.failed + counts.miscast + counts.missing
    if null_policy in ("ignore", "separate", "not_applicable"):
        return counts.passed + counts.failed + counts.miscast
    raise ValueError(f"Unsupported null policy: {null_policy}")


def compute_rule_score(inp: RuleScoringInput) -> tuple[str, float | None]:
    """Compute Rule Score according to Null Policy with Guard Clauses.

    Follows DQ_SCORING_THEORY §7:
      - 'fail': n_r = passed + failed + miscast + missing
      - 'ignore' / 'separate' / 'not_applicable': n_r = passed + failed + miscast
    Returns:
      (measurement_status, computed_score)
    """
    if not inp.is_applicable:
        return MeasurementStatus.NOT_APPLICABLE.value, None

    if not inp.has_required_metadata:
        return MeasurementStatus.NOT_MEASURABLE.value, None

    denominator = _calculate_denominator(inp.counts, inp.null_policy)
    if denominator == 0:
        return inp.zero_denominator_status, None

    score = (inp.counts.passed / denominator) * 100.0
    return MeasurementStatus.MEASURED.value, score
