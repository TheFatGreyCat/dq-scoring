from __future__ import annotations

from dq_core.models import CanonicalValidationResult, DatasetRuleBinding, MeasurementResult, RecordMeasurementSummary
from rules_engine.models import RuleEvaluationResult, RulesEngineResult


def canonicalize_rule_evaluation(
    validation_run_id: str,
    evaluation: RuleEvaluationResult,
    binding: DatasetRuleBinding,
    *,
    null_policy: str,
) -> tuple[MeasurementResult, RecordMeasurementSummary]:
    failed_count = evaluation.failed + evaluation.miscast
    missing_count = evaluation.empty
    not_applicable_count = evaluation.not_applicable
    if null_policy == "fail":
        records_in_scope = evaluation.passed + failed_count + missing_count
    elif null_policy in {"ignore", "separate"}:
        records_in_scope = evaluation.passed + failed_count
        if null_policy == "ignore":
            not_applicable_count += missing_count
    else:
        raise ValueError(f"Unsupported null_policy '{null_policy}'")

    measurement_id = f"MR-{validation_run_id}-{binding.binding_id}"
    measured = evaluation.measurement_status == "measured"
    expectation_success = None
    if measured and evaluation.threshold is not None and records_in_scope:
        expectation_success = (evaluation.passed / records_in_scope * 100) >= evaluation.threshold

    measurement = MeasurementResult(
        measurement_result_id=measurement_id,
        validation_run_id=validation_run_id,
        binding_id=binding.binding_id,
        evaluation_unit=evaluation.evaluation_unit,
        expectation_success=expectation_success,
        measurement_status=evaluation.measurement_status,
        observed_value={
            "passed": evaluation.passed,
            "failed": evaluation.failed,
            "miscast": evaluation.miscast,
            "missing": evaluation.empty,
            "not_applicable": evaluation.not_applicable,
            "records_in_scope": records_in_scope,
        },
        expected_spec={"threshold": evaluation.threshold, "null_policy": null_policy},
        failure_breakdown={"failed": evaluation.failed, "miscast": evaluation.miscast, "missing": evaluation.empty},
        backend=binding.backend,
    )
    summary = RecordMeasurementSummary(
        measurement_result_id=measurement_id,
        passed_count=evaluation.passed,
        failed_count=failed_count,
        missing_count=missing_count,
        not_applicable_count=not_applicable_count,
        records_in_scope=records_in_scope,
    )
    return measurement, summary


def canonicalize_rules_engine_result(
    validation_run_id: str,
    dataset_version_id: str,
    rules_result: RulesEngineResult,
    bindings_by_rule_id: dict[str, DatasetRuleBinding],
    null_policy_by_rule_id: dict[str, str],
) -> CanonicalValidationResult:
    measurements: list[MeasurementResult] = []
    summaries: list[RecordMeasurementSummary] = []
    for evaluation in rules_result.rule_evaluation_results:
        binding = bindings_by_rule_id[evaluation.rule_id]
        measurement, summary = canonicalize_rule_evaluation(
            validation_run_id,
            evaluation,
            binding,
            null_policy=null_policy_by_rule_id.get(evaluation.rule_id, "ignore"),
        )
        measurements.append(measurement)
        summaries.append(summary)
    return CanonicalValidationResult(validation_run_id, dataset_version_id, measurements, summaries)
