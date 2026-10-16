"""Score aggregator service combining rule results into scorecards."""

from pydantic import BaseModel, ConfigDict

from dq_scoring.core.dataset_scoring import (
    DatasetScoringInput,
    compute_dataset_score,
)
from dq_scoring.core.dimension_scoring import (
    DimensionScoringInput,
    compute_dimension_result,
)
from dq_scoring.core.models import (
    DimensionResult,
    GateEvaluationInput,
    MeasurementStatus,
    PublicationCheckInput,
    PublicationStatus,
    QualityGateStatus,
    QualityRuleResult,
    ScoringPolicy,
)
from dq_scoring.core.publication import determine_publication_status
from dq_scoring.core.quality_gate import evaluate_quality_gate


class ScoreSummaryDTO(BaseModel):
    """Aggregated scorecard summary containing scores, gate, and publication state."""

    model_config = ConfigDict(frozen=True)

    dq_score: float | None
    coverage_ratio: float | None
    quality_gate: QualityGateStatus
    publication_status: PublicationStatus
    published_score: float | None
    dimension_results: list[DimensionResult]
    all_required_dimensions_measured: bool
    has_failed_required_rules: bool
    has_unmeasured_required_rules: bool


class ScoreAggregator:
    """Service computing multi-tier scores and evaluating Quality Gate / Publication."""

    def aggregate(
        self,
        rule_results: list[QualityRuleResult],
        policy: ScoringPolicy,
        required_dimensions: set[str] | None = None,
        run_status: str = "SUCCEEDED",
    ) -> ScoreSummaryDTO:
        """Aggregate rule-level results into dimension and dataset scorecards."""
        req_dims = required_dimensions or set()
        dim_results = self._compute_all_dimension_results(
            rule_results, req_dims, policy.dimension_weights
        )

        dataset_res = compute_dataset_score(
            DatasetScoringInput(
                dimension_results=dim_results,
                dimension_weights=policy.dimension_weights,
            )
        )

        measured_dims = {
            d.dimension for d in dim_results if d.dimension_score is not None
        }
        all_req_measured = not bool(req_dims - measured_dims)

        has_failed_required = any(
            r.is_required
            and r.measurement_status == MeasurementStatus.FAILED_TO_MEASURE.value
            for r in rule_results
        )
        has_unmeasured_required = any(
            r.is_required
            and r.measurement_status
            in (
                MeasurementStatus.NOT_MEASURABLE.value,
                MeasurementStatus.INSUFFICIENT_DATA.value,
                MeasurementStatus.SKIPPED_BY_BUDGET.value,
            )
            for r in rule_results
        )

        gate_status = evaluate_quality_gate(
            GateEvaluationInput(
                rule_results=rule_results,
                dq_score=dataset_res.dq_score,
                coverage_ratio=dataset_res.coverage_ratio,
                policy=policy,
                required_dimensions=req_dims,
            )
        )

        pub_status, pub_score = determine_publication_status(
            PublicationCheckInput(
                run_status=run_status,
                gate_status=gate_status,
                dq_score=dataset_res.dq_score,
                coverage_ratio=dataset_res.coverage_ratio,
                policy=policy,
                all_required_dimensions_measured=all_req_measured,
                has_failed_required_rules=has_failed_required,
                has_unmeasured_required_rules=has_unmeasured_required,
            )
        )

        return ScoreSummaryDTO(
            dq_score=dataset_res.dq_score,
            coverage_ratio=dataset_res.coverage_ratio,
            quality_gate=gate_status,
            publication_status=pub_status,
            published_score=pub_score,
            dimension_results=dim_results,
            all_required_dimensions_measured=all_req_measured,
            has_failed_required_rules=has_failed_required,
            has_unmeasured_required_rules=has_unmeasured_required,
        )

    def _compute_all_dimension_results(
        self,
        rule_results: list[QualityRuleResult],
        required_dimensions: set[str],
        dimension_weights: dict[str, float] | None = None,
    ) -> list[DimensionResult]:
        """Compute DimensionResult for each distinct and required dimension."""
        weights = dimension_weights or {}
        distinct_dims = sorted(
            {r.dimension for r in rule_results} | required_dimensions
        )
        rules_by_dim: dict[str, list[QualityRuleResult]] = {
            d: [] for d in distinct_dims
        }
        for r in rule_results:
            rules_by_dim[r.dimension].append(r)

        return [
            compute_dimension_result(
                DimensionScoringInput(
                    dimension=dim,
                    rules=rules_by_dim.get(dim, []),
                    dimension_weight=weights.get(dim, weights.get(dim.upper(), 1.0)),
                )
            )
            for dim in distinct_dims
        ]
