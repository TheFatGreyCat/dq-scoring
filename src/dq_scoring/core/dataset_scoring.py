"""Pure domain logic for Dataset DQ Score and Coverage aggregation."""

from pydantic import BaseModel, ConfigDict, Field

from dq_scoring.core.models import (
    DatasetScoreResult,
    DimensionResult,
)

DEFAULT_DIMENSION_WEIGHT = 1.0
"""Weight for dimensions a policy does not list (equal weighting, as with no weights at all)."""


class DatasetScoringInput(BaseModel):
    """Input payload for aggregating dimensions into overall dataset DQ Score and Coverage."""

    model_config = ConfigDict(frozen=True)

    dimension_results: list[DimensionResult]
    dimension_weights: dict[str, float] = Field(default_factory=dict)


def compute_dataset_score(inp: DatasetScoringInput) -> DatasetScoreResult:
    """Compute overall Dataset DQ Score S_DQ and Coverage C_DQ per DQ_SCORING_THEORY §12."""
    weights = {
        d.dimension: inp.dimension_weights.get(d.dimension, DEFAULT_DIMENSION_WEIGHT)
        for d in inp.dimension_results
    }
    measured_dims = [
        d
        for d in inp.dimension_results
        if d.dimension_score is not None and weights.get(d.dimension, 0.0) > 0.0
    ]
    expected_dims = [
        d
        for d in inp.dimension_results
        if d.coverage_ratio is not None and weights.get(d.dimension, 0.0) > 0.0
    ]

    sum_measured_alpha = sum(weights[d.dimension] for d in measured_dims)
    sum_expected_alpha = sum(weights[d.dimension] for d in expected_dims)

    dq_score: float | None = None
    if sum_measured_alpha > 0:
        weighted_dim_sum = sum(
            weights[d.dimension] * (d.dimension_score or 0.0) for d in measured_dims
        )
        dq_score = weighted_dim_sum / sum_measured_alpha

    coverage_ratio: float | None = None
    if sum_expected_alpha > 0:
        weighted_cov_sum = sum(
            weights[d.dimension] * (d.coverage_ratio or 0.0) for d in expected_dims
        )
        coverage_ratio = weighted_cov_sum / sum_expected_alpha

    return DatasetScoreResult(
        dq_score=dq_score,
        coverage_ratio=coverage_ratio,
        dimension_results=inp.dimension_results,
    )
