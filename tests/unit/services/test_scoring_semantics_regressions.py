"""Regression tests for scoring-semantics defects found in the audit (M1-M4)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
from dq_scoring.core.dataset_scoring import DatasetScoringInput, compute_dataset_score
from dq_scoring.core.dimension_scoring import (
    DimensionScoringInput,
    compute_dimension_result,
)
from dq_scoring.core.entities import QualityRule, RuleExecutionOutput
from dq_scoring.core.models import (
    DimensionResult,
    MeasurementStatus,
    PublicationStatus,
    QualityGateStatus,
    QualityRuleResult,
    RuleCounts,
    ScoringPolicy,
)
from dq_scoring.services.validation_service import ValidationService
from tests.unit.services.test_evaluation_orchestrator import _create_setup
from tests.unit.services.test_validation_service import _sample_snapshot


@pytest.mark.parametrize("status", [MeasurementStatus.INSUFFICIENT_DATA, MeasurementStatus.SKIPPED_BY_BUDGET])
def test_unmeasured_compute_statuses_are_not_rescored_as_measured(status: MeasurementStatus) -> None:
    """M1: only MEASURED outputs are scored; other statuses keep their status and no score."""
    compute = InMemoryComputeAdapter()
    rule = QualityRule(rule_id=uuid4(), rule_code="R", dimension="COMPLETENESS", rule_type="NON_NULL")
    compute.set_rule_output(
        rule.rule_id,
        RuleExecutionOutput(rule_id=rule.rule_id, counts=RuleCounts(passed=5, total_observed=5), status=status),
    )
    [result] = ValidationService(compute).validate_ruleset(_sample_snapshot(), [rule])
    assert result.measurement_status == status.value
    assert result.computed_score is None


def _result(rule_id: str, *, score: float | None, status: str = "MEASURED", score_enabled: bool = True, weight: float = 1.0) -> QualityRuleResult:
    return QualityRuleResult(
        rule_id=rule_id,
        dimension="VALIDITY",
        measurement_status=status,
        score_enabled=score_enabled,
        contribution_weight=weight,
        computed_score=score,
    )


def test_gate_only_rules_do_not_reduce_dimension_coverage() -> None:
    """M4: a gate-only rule (score_enabled=False) is never 'measured' for scoring, so it is not 'expected'."""
    dim = compute_dimension_result(
        DimensionScoringInput(
            dimension="VALIDITY",
            rules=[_result("scored", score=90.0), _result("gate_only", score=100.0, score_enabled=False)],
        )
    )
    assert dim.coverage_ratio == pytest.approx(1.0)
    assert dim.dimension_score == pytest.approx(90.0)


def test_dimensions_missing_from_policy_weights_default_to_equal_weight() -> None:
    """M3: a partial weight map must not silently drop unlisted dimensions from score and coverage."""
    dims = [
        DimensionResult(dimension="COMPLETENESS", dimension_score=100.0, coverage_ratio=1.0),
        DimensionResult(dimension="VALIDITY", dimension_score=50.0, coverage_ratio=1.0),
    ]
    result = compute_dataset_score(DatasetScoringInput(dimension_results=dims, dimension_weights={"COMPLETENESS": 1.0}))
    assert result.dq_score == pytest.approx(75.0)


def test_dimension_with_expected_but_unmeasured_rules_withholds_the_score() -> None:
    """M2: high coverage elsewhere must not publish a score while a ruled dimension is unmeasured."""
    compute, _store, queue, orchestrator, spec = _create_setup()
    measured = [QualityRule(rule_id=uuid4(), rule_code=f"C{i}", dimension="COMPLETENESS", rule_type="NON_NULL") for i in range(9)]
    unmeasured = QualityRule(rule_id=uuid4(), rule_code="V", dimension="VALIDITY", rule_type="NON_NULL")
    compute.set_rule_output(
        unmeasured.rule_id,
        RuleExecutionOutput(rule_id=unmeasured.rule_id, counts=RuleCounts(), status=MeasurementStatus.NOT_MEASURABLE),
    )
    spec = spec.model_copy(
        update={
            "rules": [*measured, unmeasured],
            "outlier_columns": [],
            # COMPLETENESS dominates coverage (0.9 >= 0.8 threshold) but VALIDITY has nothing measured.
            "policy": ScoringPolicy(dimension_weights={"COMPLETENESS": 9.0, "VALIDITY": 1.0}),
        }
    )
    queue.enqueue_run(spec, idempotency_key="m2")
    assessment = orchestrator.execute_leased_run(queue.claim_next_run("w"))
    assert assessment.coverage_ratio == pytest.approx(0.9)
    assert assessment.quality_gate == QualityGateStatus.INSUFFICIENT_EVIDENCE
    assert assessment.publication_status == PublicationStatus.WITHHELD
    assert assessment.dq_score is None
