"""Unit tests for Dataset DQ Score and Coverage aggregation."""

import pytest

from dq_scoring.core.dataset_scoring import (
    DatasetScoringInput,
    compute_dataset_score,
)
from dq_scoring.core.models import (
    DimensionResult,
    StandardDimension,
)


def test_dataset_score_all_dimensions():
    """All dimensions present compute weighted score and weighted coverage."""
    dim_results = [
        DimensionResult(
            dimension=StandardDimension.ACCURACY.value,
            dimension_score=90.0,
            coverage_ratio=1.0,
        ),
        DimensionResult(
            dimension=StandardDimension.COMPLETENESS.value,
            dimension_score=80.0,
            coverage_ratio=1.0,
        ),
    ]
    weights = {
        StandardDimension.ACCURACY.value: 2.0,
        StandardDimension.COMPLETENESS.value: 1.0,
    }
    inp = DatasetScoringInput(
        dimension_results=dim_results,
        dimension_weights=weights,
    )
    res = compute_dataset_score(inp)
    # (2*90 + 1*80) / 3 = 260 / 3 = 86.6666...
    assert res.dq_score == pytest.approx(86.66666666666667)
    assert res.coverage_ratio == pytest.approx(1.0)


def test_dataset_score_renormalization_missing_dimension():
    """Missing dimension (None) renormalizes over measured dimensions only; coverage reflects gap."""
    dim_results = [
        DimensionResult(
            dimension=StandardDimension.ACCURACY.value,
            dimension_score=90.0,
            coverage_ratio=1.0,
        ),
        DimensionResult(
            dimension=StandardDimension.COMPLETENESS.value,
            dimension_score=None,
            coverage_ratio=0.0,
        ),
    ]
    weights = {
        StandardDimension.ACCURACY.value: 1.0,
        StandardDimension.COMPLETENESS.value: 1.0,
    }
    inp = DatasetScoringInput(
        dimension_results=dim_results,
        dimension_weights=weights,
    )
    res = compute_dataset_score(inp)
    # Measured: only ACCURACY -> score = 90.0
    # Expected: ACCURACY (cov=1.0) + COMPLETENESS (cov=0.0) -> coverage = (1*1.0 + 1*0.0)/2 = 0.5
    assert res.dq_score == pytest.approx(90.0)
    assert res.coverage_ratio == pytest.approx(0.5)


def test_dataset_score_no_measured_dimensions():
    """When no dimension has a score, dq_score is None (never forced to 0)."""
    dim_results = [
        DimensionResult(
            dimension=StandardDimension.ACCURACY.value,
            dimension_score=None,
            coverage_ratio=0.0,
        ),
    ]
    weights = {StandardDimension.ACCURACY.value: 1.0}
    inp = DatasetScoringInput(
        dimension_results=dim_results,
        dimension_weights=weights,
    )
    res = compute_dataset_score(inp)
    assert res.dq_score is None
    assert res.coverage_ratio == pytest.approx(0.0)
