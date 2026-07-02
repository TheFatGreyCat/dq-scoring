from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from rules_engine.models import RuleEvaluationResult, RulesEngineResult

from scoring.models import (
    DatasetScoreHistory,
    DimensionScoreHistory,
    RuleScoreHistory,
    ScoreRun,
    ScoringConfig,
    ScoringResult,
    iso,
)


def score_rules_engine_result(
    rules_result: RulesEngineResult,
    scoring_config: ScoringConfig,
    scoring_config_path: str | None = None,
) -> ScoringResult:
    run_timestamp = iso(datetime.now(timezone.utc)) or ""
    run_id = f"SRUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    rule_config_by_id = {rule.rule_id: rule for rule in rules_result.rule_configs}

    rule_scores: list[RuleScoreHistory] = []
    for evaluation in rules_result.rule_evaluation_results:
        rule_config = rule_config_by_id.get(evaluation.rule_id)
        if rule_config is None or not rule_config.score_enabled:
            continue
        rule_scores.append(_score_rule(run_id, evaluation, scoring_config.warning_margin))

    dimension_scores = _score_dimensions(
        run_id,
        rules_result.rule_run.dataset_id,
        rule_scores,
        scoring_config,
    )
    dataset_score = _score_dataset(
        run_id,
        rules_result.rule_run.dataset_id,
        run_timestamp,
        rules_result.rule_run.dataset_version,
        rule_scores,
        dimension_scores,
        scoring_config,
    )

    measured_rule_count = sum(1 for score in rule_scores if score.measurement_status == "measured")
    score_run = ScoreRun(
        run_id=run_id,
        rule_run_id=rules_result.rule_run.rule_run_id,
        dataset_id=rules_result.rule_run.dataset_id,
        run_timestamp=run_timestamp,
        scoring_config_path=scoring_config_path,
        status="success" if dataset_score.dq_core_score is not None else "not_scored",
        rules_total=len(rule_scores),
        rules_scored=measured_rule_count,
        dimensions_measured=len(dataset_score.measured_dimensions),
    )
    return ScoringResult(
        score_run=score_run,
        rule_score_history=rule_scores,
        dimension_score_history=dimension_scores,
        dataset_score_history=dataset_score,
    )


def _score_rule(run_id: str, evaluation: RuleEvaluationResult, warning_margin: float) -> RuleScoreHistory:
    rule_score: float | None = None
    quality_status = evaluation.measurement_status
    if evaluation.measurement_status == "measured" and evaluation.total_records_in_scope > 0:
        rule_score = round(evaluation.passed / evaluation.total_records_in_scope * 100, 6)
        quality_status = _quality_status(rule_score, evaluation.threshold, warning_margin)

    return RuleScoreHistory(
        run_id=run_id,
        dataset_id=evaluation.dataset_id,
        rule_id=evaluation.rule_id,
        dimension=evaluation.dimension,
        target_column=evaluation.target_column,
        passed=evaluation.passed,
        failed=evaluation.failed,
        miscast=evaluation.miscast,
        empty=evaluation.empty,
        not_applicable=evaluation.not_applicable,
        total_records_in_scope=evaluation.total_records_in_scope,
        rule_score=rule_score,
        threshold=evaluation.threshold,
        measurement_status=evaluation.measurement_status,
        quality_status=quality_status,
    )


def _quality_status(rule_score: float, threshold: float | None, warning_margin: float) -> str:
    if threshold is None:
        return "measured"
    if rule_score >= threshold:
        return "pass"
    if rule_score >= threshold - warning_margin:
        return "warning"
    return "fail"


def _score_dimensions(
    run_id: str,
    dataset_id: str,
    rule_scores: list[RuleScoreHistory],
    scoring_config: ScoringConfig,
) -> list[DimensionScoreHistory]:
    measured_by_dimension: dict[str, list[RuleScoreHistory]] = defaultdict(list)
    total_by_dimension: dict[str, list[RuleScoreHistory]] = defaultdict(list)
    for rule_score in rule_scores:
        if not rule_score.dimension:
            continue
        total_by_dimension[rule_score.dimension].append(rule_score)
        if rule_score.measurement_status == "measured" and rule_score.rule_score is not None:
            measured_by_dimension[rule_score.dimension].append(rule_score)

    measured_dimensions = set(measured_by_dimension)
    measured_weight_sum = sum(
        weight for dimension, weight in scoring_config.dimension_weights.items() if dimension in measured_dimensions
    )

    dimension_scores: list[DimensionScoreHistory] = []
    for dimension, original_weight in scoring_config.dimension_weights.items():
        measured_rules = measured_by_dimension.get(dimension, [])
        all_rules = total_by_dimension.get(dimension, [])
        is_measured = bool(measured_rules)
        normalized_weight = original_weight / measured_weight_sum if is_measured and measured_weight_sum else 0.0
        dimension_score = _weighted_rule_average(measured_rules, scoring_config.rule_weights) if is_measured else None
        dimension_scores.append(
            DimensionScoreHistory(
                run_id=run_id,
                dataset_id=dataset_id,
                dimension=dimension,
                dimension_score=dimension_score,
                original_dimension_weight=original_weight,
                dimension_weight=round(normalized_weight, 6),
                is_measured=is_measured,
                measurement_status="measured" if is_measured else "not_measured",
                rules_total=len(all_rules),
                rules_failed=sum(1 for score in measured_rules if score.quality_status == "fail"),
                rules_warning=sum(1 for score in measured_rules if score.quality_status == "warning"),
                rules_passed=sum(1 for score in measured_rules if score.quality_status == "pass"),
            )
        )
    return dimension_scores


def _weighted_rule_average(rule_scores: list[RuleScoreHistory], rule_weights: dict[str, float]) -> float:
    weighted_rules = [(score, rule_weights.get(score.rule_id, 1.0)) for score in rule_scores]
    weight_sum = sum(weight for _, weight in weighted_rules)
    if weight_sum <= 0:
        weight_sum = float(len(weighted_rules))
        weighted_rules = [(score, 1.0) for score, _ in weighted_rules]
    score = sum((score.rule_score or 0.0) * weight for score, weight in weighted_rules) / weight_sum
    return round(score, 6)


def _score_dataset(
    run_id: str,
    dataset_id: str,
    run_timestamp: str,
    dataset_version: str | None,
    rule_scores: list[RuleScoreHistory],
    dimension_scores: list[DimensionScoreHistory],
    scoring_config: ScoringConfig,
) -> DatasetScoreHistory:
    measured_dimensions = [score.dimension for score in dimension_scores if score.is_measured]
    excluded_dimensions = [score.dimension for score in dimension_scores if not score.is_measured]
    measured_scores = [score for score in dimension_scores if score.is_measured and score.dimension_score is not None]
    dq_core_score = None
    if measured_scores:
        dq_core_score = round(sum((score.dimension_score or 0.0) * score.dimension_weight for score in measured_scores), 6)

    return DatasetScoreHistory(
        run_id=run_id,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        run_timestamp=run_timestamp,
        dq_core_score=dq_core_score,
        quality_gate_status=_quality_gate_status(dq_core_score, scoring_config),
        total_records=max((score.total_records_in_scope for score in rule_scores), default=0),
        rules_total=len(rule_scores),
        rules_failed=sum(1 for score in rule_scores if score.quality_status == "fail"),
        measured_dimensions=measured_dimensions,
        excluded_dimensions=excluded_dimensions,
    )


def _quality_gate_status(dq_core_score: float | None, scoring_config: ScoringConfig) -> str:
    if dq_core_score is None:
        return "not_scored"
    if dq_core_score >= scoring_config.quality_gate_pass_threshold:
        return "pass"
    if dq_core_score >= scoring_config.quality_gate_warning_threshold:
        return "warning"
    return "fail"

