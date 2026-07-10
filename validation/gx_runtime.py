from __future__ import annotations

import contextlib
import io
import re
from typing import Any

import pandas as pd

from dq_core.models import DatasetRuleBinding, MeasurementResult, RecordMeasurementSummary, ValidationIssueSample, iso, utc_now
from validation.planner import GX_SUPPORTED_OPERATORS


class GxRuntimeEvaluator:
    """GX-backed canonical adapter for standard dataframe expectations."""

    def __init__(self) -> None:
        self.last_issue_samples: list[ValidationIssueSample] = []

    def evaluate(
        self,
        dataframe: pd.DataFrame,
        validation_run_id: str,
        binding: DatasetRuleBinding,
        operator: str,
        parameters: dict[str, Any],
        *,
        null_policy: str,
        rule_code: str | None = None,
        sample_limit: int = 20,
    ) -> tuple[MeasurementResult, RecordMeasurementSummary]:
        if operator not in GX_SUPPORTED_OPERATORS:
            raise ValueError(f"Operator '{operator}' is not supported by GX runtime")
        if not binding.target_columns:
            raise ValueError(f"Binding '{binding.binding_id}' has no target column")

        column = binding.target_columns[0]
        gx_raw = _run_gx_expectation(dataframe, binding, operator, parameters)
        statuses = pd.Series("not_applicable", index=dataframe.index, dtype="object")
        empty = dataframe[column].isna() | dataframe[column].astype(str).str.strip().eq("")
        eligible = ~empty
        if null_policy == "fail":
            statuses.loc[empty] = "empty"
        elif null_policy in {"ignore", "separate", "not_applicable"}:
            statuses.loc[empty] = "not_applicable" if null_policy in {"ignore", "not_applicable"} else "empty"
        else:
            raise ValueError(f"Unsupported null_policy '{null_policy}'")

        if operator in {"not_null", "not_blank"}:
            statuses.loc[eligible] = "passed"
        elif operator == "regex":
            pattern = re.compile(str(parameters["pattern"]))
            matched = dataframe.loc[eligible, column].astype(str).map(lambda value: bool(pattern.fullmatch(value)))
            statuses.loc[eligible] = matched.map(lambda value: "passed" if value else "failed")
        elif operator == "domain":
            values = {str(item) for item in parameters.get("values", parameters.get("allowed_values", []))}
            matched = dataframe.loc[eligible, column].astype(str).isin(values)
            statuses.loc[eligible] = matched.map(lambda value: "passed" if value else "failed")
        elif operator == "range":
            converted = pd.to_numeric(dataframe.loc[eligible, column].astype(str).str.replace(",", "", regex=False), errors="coerce")
            condition = pd.Series(True, index=converted.index)
            if "min_value" in parameters:
                condition &= converted >= float(parameters["min_value"])
            if "max_value" in parameters:
                condition &= converted <= float(parameters["max_value"])
            statuses.loc[converted.index[converted.isna()]] = "failed"
            statuses.loc[condition.index[~converted.isna()]] = condition[~converted.isna()].map(lambda value: "passed" if value else "failed")
        elif operator == "length":
            lengths = dataframe.loc[eligible, column].astype(str).str.len()
            condition = pd.Series(True, index=lengths.index)
            if "exact_length" in parameters:
                condition &= lengths == int(parameters["exact_length"])
            if "min_length" in parameters:
                condition &= lengths >= int(parameters["min_length"])
            if "max_length" in parameters:
                condition &= lengths <= int(parameters["max_length"])
            statuses.loc[eligible] = condition.map(lambda value: "passed" if value else "failed")
        elif operator == "type_check":
            expected = str(parameters.get("expected_type") or parameters.get("data_type") or parameters.get("value_format")).lower()
            if expected in {"number", "numeric", "float", "integer", "int", "currency", "percentage"}:
                converted = pd.to_numeric(dataframe.loc[eligible, column].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
                statuses.loc[eligible] = converted.notna().map(lambda value: "passed" if value else "failed")
            elif expected in {"datetime", "date", "timestamp"}:
                converted = pd.to_datetime(dataframe.loc[eligible, column], errors="coerce", utc=True)
                statuses.loc[eligible] = converted.notna().map(lambda value: "passed" if value else "failed")
            else:
                statuses.loc[eligible] = "passed"
        elif operator == "uniqueness":
            duplicated = dataframe.loc[eligible, column].duplicated(keep=False)
            statuses.loc[duplicated.index] = (~duplicated).map(lambda value: "passed" if value else "failed")
        elif operator == "not_future":
            converted = pd.to_datetime(dataframe.loc[eligible, column], errors="coerce", utc=True)
            now = pd.Timestamp.now(tz="UTC")
            condition = converted.notna() & (converted <= now)
            statuses.loc[eligible] = condition.map(lambda value: "passed" if value else "failed")

        measurement, summary = _canonical(validation_run_id, binding, operator, parameters, statuses, gx_raw)
        self.last_issue_samples = _issue_samples(dataframe, statuses, validation_run_id, binding, operator, parameters, rule_code, sample_limit)
        return measurement, summary


def _run_gx_expectation(
    dataframe: pd.DataFrame,
    binding: DatasetRuleBinding,
    operator: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    import great_expectations as gx

    column = binding.target_columns[0]
    context = gx.get_context(mode="ephemeral")
    datasource = context.data_sources.add_pandas("dq_pandas_source")
    asset = datasource.add_dataframe_asset(f"asset__{binding.dataset_version_id}")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_dataframe")
    batch = batch_definition.get_batch(batch_parameters={"dataframe": dataframe})
    suite = gx.ExpectationSuite(name=f"suite__{binding.dataset_version_id}__{binding.binding_id}")
    validator = context.get_validator(batch=batch, expectation_suite=suite)
    kwargs = {"column": column, "result_format": "SUMMARY"}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if operator in {"not_null", "not_blank"}:
            result = validator.expect_column_values_to_not_be_null(**kwargs)
        elif operator == "regex":
            result = validator.expect_column_values_to_match_regex(regex=str(parameters["pattern"]), **kwargs)
        elif operator == "domain":
            result = validator.expect_column_values_to_be_in_set(value_set=list(parameters.get("values", parameters.get("allowed_values", []))), **kwargs)
        elif operator == "range":
            result = validator.expect_column_values_to_be_between(min_value=parameters.get("min_value"), max_value=parameters.get("max_value"), **kwargs)
        elif operator == "length":
            result = validator.expect_column_value_lengths_to_be_between(
                min_value=parameters.get("min_length", parameters.get("exact_length")),
                max_value=parameters.get("max_length", parameters.get("exact_length")),
                **kwargs,
            )
        elif operator == "type_check":
            result = validator.expect_column_values_to_not_be_null(**kwargs)
        elif operator == "uniqueness":
            result = validator.expect_column_values_to_be_unique(**kwargs)
        elif operator == "not_future":
            result = validator.expect_column_values_to_not_be_null(**kwargs)
        else:
            raise ValueError(f"Operator '{operator}' is not supported by GX runtime")
    return {"success": bool(result.success), "result": dict(result.result or {})}


def _canonical(
    validation_run_id: str,
    binding: DatasetRuleBinding,
    operator: str,
    parameters: dict[str, Any],
    statuses: pd.Series,
    gx_raw: dict[str, Any],
) -> tuple[MeasurementResult, RecordMeasurementSummary]:
    counts = statuses.value_counts().to_dict()
    passed = int(counts.get("passed", 0))
    failed = int(counts.get("failed", 0))
    missing = int(counts.get("empty", 0))
    not_applicable = int(counts.get("not_applicable", 0))
    measurement_id = f"MR-{validation_run_id}-{binding.binding_id}"
    records_in_scope = passed + failed
    measurement = MeasurementResult(
        measurement_result_id=measurement_id,
        validation_run_id=validation_run_id,
        binding_id=binding.binding_id,
        evaluation_unit="record",
        expectation_success=failed == 0,
        measurement_status="measured",
        observed_value={"passed": passed, "failed": failed, "missing": missing, "not_applicable": not_applicable, "gx_result": gx_raw},
        expected_spec={"operator": operator, "parameters": parameters},
        failure_breakdown={"failed": failed, "missing": missing},
        backend="gx",
    )
    summary = RecordMeasurementSummary(measurement_id, passed, failed, missing, not_applicable, records_in_scope)
    return measurement, summary


def _issue_samples(
    dataframe: pd.DataFrame,
    statuses: pd.Series,
    validation_run_id: str,
    binding: DatasetRuleBinding,
    operator: str,
    parameters: dict[str, Any],
    rule_code: str | None,
    sample_limit: int,
) -> list[ValidationIssueSample]:
    sampled_at = iso(utc_now()) or ""
    indexes = statuses[statuses.isin({"failed", "empty", "miscast"})].head(sample_limit).index
    target_column = binding.target_columns[0] if binding.target_columns else None
    samples: list[ValidationIssueSample] = []
    for index in indexes:
        actual_value = str(dataframe.at[index, target_column]) if target_column and target_column in dataframe.columns else None
        samples.append(
            ValidationIssueSample(
                validation_run_id=validation_run_id,
                binding_id=binding.binding_id,
                record_key=str(index),
                target_column=target_column,
                actual_value=actual_value,
                expected_condition=_expected_condition(operator, parameters, rule_code),
                issue_type=str(statuses.loc[index]),
                rule_code=rule_code,
                sampled_at=sampled_at,
            )
        )
    return samples


def _expected_condition(operator: str, parameters: dict[str, Any], rule_code: str | None) -> str:
    if rule_code:
        return rule_code
    if operator == "regex":
        return f"match regex {parameters.get('pattern')}"
    if operator == "range":
        return f"between {parameters.get('min_value')} and {parameters.get('max_value')}"
    return operator


