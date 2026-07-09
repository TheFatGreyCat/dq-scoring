from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from dq_core.models import CanonicalValidationResult, DatasetRuleBinding, RuleTemplate, ScoringPolicy


@dataclass(frozen=True)
class RuleScoreV2:
    binding_id: str
    dimension: str
    target_columns: list[str]
    rule_score: float | None
    measurement_status: str
    quality_status: str
    base_rule_weight: float
    severity_weight: float
    criticality_weight: float
    effective_weight: float
    explanation: dict[str, object]


@dataclass(frozen=True)
class DimensionScoreV2:
    dimension: str
    dimension_score: float | None
    original_dimension_weight: float
    normalized_dimension_weight: float
    measurement_status: str


@dataclass(frozen=True)
class DatasetScoreV2:
    dataset_dq_score: float | None
    quality_gate_status: str
    measured_dimensions: list[str]
    excluded_dimensions: list[str]
    gate_failures: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class ScoringV2Result:
    score_run_id: str
    validation_run_id: str
    scoring_policy_id: str
    rule_scores: list[RuleScoreV2]
    dimension_scores: list[DimensionScoreV2]
    dataset_score: DatasetScoreV2


def calculate_scores(
    validation: CanonicalValidationResult,
    policy: ScoringPolicy,
    bindings_by_id: dict[str, DatasetRuleBinding],
    templates_by_id: dict[str, RuleTemplate],
    field_roles_by_column: dict[str, set[str]] | None = None,
) -> ScoringV2Result:
    field_roles_by_column = field_roles_by_column or {}
    summaries = validation.summary_by_measurement_id()
    rule_scores: list[RuleScoreV2] = []
    for measurement in validation.measurement_results:
        binding = bindings_by_id[measurement.binding_id]
        template = templates_by_id[binding.rule_template_id]
        summary = summaries[measurement.measurement_result_id]
        score = _rule_score(binding, measurement.observed_value, summary)
        criticality = _criticality(binding.target_columns, field_roles_by_column)
        severity_weight = policy.severity_weights.get(binding.severity.lower(), 1.0)
        criticality_weight = policy.criticality_weights.get(criticality, 1.0)
        base_weight = template.base_rule_weight
        effective_weight = base_weight * severity_weight * criticality_weight
        quality_status = _rule_quality(score, binding.scoring_pass_threshold, measurement.measurement_status, binding.scoring_method)
        explanation = {
            "base_score": score,
            "base_rule_weight": base_weight,
            "severity_weight": severity_weight,
            "criticality_weight": criticality_weight,
            "effective_weight": round(effective_weight, 6),
            "field_roles": sorted(_roles(binding.target_columns, field_roles_by_column)),
            "criticality": criticality,
            "scoring_method": binding.scoring_method,
        }
        rule_scores.append(
            RuleScoreV2(
                binding_id=binding.binding_id,
                dimension=template.dimension,
                target_columns=binding.target_columns,
                rule_score=score,
                measurement_status=measurement.measurement_status,
                quality_status=quality_status,
                base_rule_weight=base_weight,
                severity_weight=severity_weight,
                criticality_weight=criticality_weight,
                effective_weight=round(effective_weight, 6),
                explanation=explanation,
            )
        )

    dimension_scores = _dimension_scores(rule_scores, bindings_by_id, templates_by_id, policy)
    dataset_score = _dataset_score(rule_scores, dimension_scores, bindings_by_id, templates_by_id, policy, field_roles_by_column)
    return ScoringV2Result(
        score_run_id=f"SRUN2-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        validation_run_id=validation.validation_run_id,
        scoring_policy_id=policy.scoring_policy_id,
        rule_scores=rule_scores,
        dimension_scores=dimension_scores,
        dataset_score=dataset_score,
    )


def _rule_score(binding: DatasetRuleBinding, observed: dict[str, object], summary) -> float | None:
    if binding.scoring_method == "gate_only":
        return None
    if binding.scoring_method == "freshness_decay":
        lag = observed.get("freshness_lag_hours")
        sla = observed.get("max_freshness_lag_hours")
        if lag is None or sla in {None, 0}:
            return None
        lag_value = float(lag)
        sla_value = float(sla)
        if lag_value <= sla_value:
            return 100.0
        if lag_value > 2 * sla_value:
            return 0.0
        return round((1 - ((lag_value - sla_value) / sla_value)) * 100, 6)
    if summary.records_in_scope <= 0:
        return None
    return round(summary.passed_count / summary.records_in_scope * 100, 6)


def _rule_quality(score: float | None, threshold: float | None, measurement_status: str, scoring_method: str) -> str:
    if measurement_status != "measured":
        return measurement_status
    if scoring_method == "gate_only":
        return "measured"
    if score is None:
        return "not_measured"
    if threshold is None:
        return "measured"
    return "pass" if score >= threshold else "fail"


def _dimension_scores(
    rule_scores: list[RuleScoreV2],
    bindings_by_id: dict[str, DatasetRuleBinding],
    templates_by_id: dict[str, RuleTemplate],
    policy: ScoringPolicy,
) -> list[DimensionScoreV2]:
    measured_dimensions: set[str] = set()
    raw_scores: dict[str, float | None] = {}
    for dimension in policy.dimension_weights:
        scored = [
            score
            for score in rule_scores
            if score.dimension == dimension
            and score.rule_score is not None
            and score.measurement_status == "measured"
            and bindings_by_id[score.binding_id].score_enabled
            and bindings_by_id[score.binding_id].scoring_method != "gate_only"
        ]
        if not scored:
            raw_scores[dimension] = None
            continue
        measured_dimensions.add(dimension)
        weight_sum = sum(score.effective_weight for score in scored)
        raw_scores[dimension] = round(sum((score.rule_score or 0.0) * score.effective_weight for score in scored) / weight_sum, 6)

    measured_weight_sum = sum(policy.dimension_weights[dimension] for dimension in measured_dimensions)
    result: list[DimensionScoreV2] = []
    for dimension, original_weight in policy.dimension_weights.items():
        is_measured = dimension in measured_dimensions
        normalized = original_weight / measured_weight_sum if is_measured and measured_weight_sum else 0.0
        result.append(
            DimensionScoreV2(
                dimension=dimension,
                dimension_score=raw_scores[dimension],
                original_dimension_weight=original_weight,
                normalized_dimension_weight=round(normalized, 6),
                measurement_status="measured" if is_measured else "not_measured",
            )
        )
    return result


def _dataset_score(
    rule_scores: list[RuleScoreV2],
    dimension_scores: list[DimensionScoreV2],
    bindings_by_id: dict[str, DatasetRuleBinding],
    templates_by_id: dict[str, RuleTemplate],
    policy: ScoringPolicy,
    field_roles_by_column: dict[str, set[str]],
) -> DatasetScoreV2:
    measured = [score for score in dimension_scores if score.measurement_status == "measured" and score.dimension_score is not None]
    measured_dimensions = [score.dimension for score in measured]
    excluded_dimensions = [score.dimension for score in dimension_scores if score.measurement_status != "measured"]
    if not measured:
        return DatasetScoreV2(None, "not_scored", [], excluded_dimensions, [{"reason": "no measured rule"}])
    dataset_score = round(sum((score.dimension_score or 0.0) * score.normalized_dimension_weight for score in measured), 6)
    gate_failures = _gate_failures(rule_scores, bindings_by_id, templates_by_id, field_roles_by_column)
    if gate_failures:
        status = "fail"
    elif dataset_score >= policy.quality_gate_pass_threshold:
        status = "pass"
    elif dataset_score >= policy.quality_gate_warning_threshold:
        status = "warning"
    else:
        status = "fail"
    return DatasetScoreV2(dataset_score, status, measured_dimensions, excluded_dimensions, gate_failures)


def _gate_failures(
    rule_scores: list[RuleScoreV2],
    bindings_by_id: dict[str, DatasetRuleBinding],
    templates_by_id: dict[str, RuleTemplate],
    field_roles_by_column: dict[str, set[str]],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for score in rule_scores:
        binding = bindings_by_id[score.binding_id]
        template = templates_by_id[binding.rule_template_id]
        roles = _roles(binding.target_columns, field_roles_by_column)
        hard_gate = binding.gate_enabled
        hard_gate = hard_gate or (template.dimension == "Uniqueness" and "business_key" in roles)
        hard_gate = hard_gate or (template.dimension == "Completeness" and "mandatory" in roles and _criticality(binding.target_columns, field_roles_by_column) == "Critical")
        if hard_gate and score.quality_status == "fail":
            failures.append({"binding_id": score.binding_id, "dimension": template.dimension, "reason": "hard_gate_failed"})
    return failures


def _criticality(target_columns: list[str], roles_by_column: dict[str, set[str]]) -> str:
    roles = _roles(target_columns, roles_by_column)
    if "business_key" in roles or {"cde", "mandatory"}.issubset(roles):
        return "Critical"
    if "cde" in roles or "mandatory" in roles or {"identifier", "mandatory"}.issubset(roles):
        return "High"
    if "identifier" in roles:
        return "Medium"
    return "Normal"


def _roles(target_columns: list[str], roles_by_column: dict[str, set[str]]) -> set[str]:
    roles: set[str] = set()
    for column in target_columns:
        roles.update(roles_by_column.get(column, set()))
    return roles
