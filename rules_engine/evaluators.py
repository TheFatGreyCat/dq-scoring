from __future__ import annotations

import re
from datetime import timezone
from typing import Any

import pandas as pd

from profiling.models import DatasetConfig

from rules_engine.config import _domain_values, _key_columns
from rules_engine.models import RuleConfig, RuleEvaluationResult, RuleIssueSample, iso, utc_now


ISSUE_TYPES = {"empty", "failed", "miscast"}
NUMERIC_VALUE_FORMATS = {"number", "numeric", "float", "integer", "int", "currency", "percentage"}


class RuleEvaluator:
    def evaluate(self, dataframe: pd.DataFrame, dataset_config: DatasetConfig, rule_config: RuleConfig) -> RuleEvaluationResult:
        result, _ = self.evaluate_with_samples(dataframe, dataset_config, rule_config, rule_run_id="RRUN-EVALUATE")
        return result

    def evaluate_with_samples(
        self,
        dataframe: pd.DataFrame,
        dataset_config: DatasetConfig,
        rule_config: RuleConfig,
        rule_run_id: str,
        sample_limit: int = 20,
    ) -> tuple[RuleEvaluationResult, list[RuleIssueSample]]:
        statuses, evaluation_unit = self._evaluate_statuses(dataframe, dataset_config, rule_config)
        result = _result_from_statuses(rule_run_id, rule_config, evaluation_unit, statuses)
        samples = _sample_issues(dataframe, statuses, dataset_config, rule_config, rule_run_id, sample_limit)
        return result, samples

    def _evaluate_statuses(
        self, dataframe: pd.DataFrame, dataset_config: DatasetConfig, rule: RuleConfig
    ) -> tuple[pd.Series, str]:
        if rule.rule_type in {"not_null", "not_blank"}:
            return self._not_empty(dataframe, rule), "record"
        if rule.rule_type == "regex":
            return self._regex(dataframe, rule), "record"
        if rule.rule_type == "length":
            return self._length(dataframe, rule), "record"
        if rule.rule_type == "domain":
            return self._domain(dataframe, rule), "record"
        if rule.rule_type == "type_check":
            return self._type_check(dataframe, rule), "record"
        if rule.rule_type in {"range", "plausibility_range"}:
            return self._range(dataframe, rule), "record"
        if rule.rule_type == "date_parseable":
            return self._date_parseable(dataframe, rule), "record"
        if rule.rule_type == "not_future":
            return self._not_future(dataframe, rule), "record"
        if rule.rule_type in {"uniqueness", "composite_uniqueness"}:
            return self._uniqueness(dataframe, dataset_config, rule), "key"
        if rule.rule_type == "full_row_duplicate":
            return self._full_row_duplicate(dataframe, rule), "record"
        if rule.rule_type == "comparison":
            return self._comparison(dataframe, rule), "record"
        if rule.rule_type == "conditional_required":
            return self._conditional_required(dataframe, rule), "record"
        if rule.rule_type == "freshness":
            return self._freshness(dataframe, dataset_config, rule), "dataset_run"
        raise ValueError(f"Unsupported rule_type '{rule.rule_type}'")

    def _not_empty(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, in_scope, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        empty = in_scope & _is_empty(dataframe[rule.target_column])
        if rule.null_policy == "ignore":
            statuses.loc[empty] = "not_applicable"
        else:
            statuses.loc[empty] = "empty"
        statuses.loc[eligible] = "passed"
        return statuses

    def _regex(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        pattern = re.compile(str(rule.parameters["pattern"]))
        matched = dataframe.loc[eligible, rule.target_column].astype(str).map(lambda value: bool(pattern.fullmatch(value)))
        statuses.loc[eligible] = _pass_fail(matched)
        return statuses

    def _length(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        lengths = dataframe.loc[eligible, rule.target_column].astype(str).str.len()
        condition = pd.Series(True, index=lengths.index)
        if "exact_length" in rule.parameters:
            condition &= lengths == int(rule.parameters["exact_length"])
        if "min_length" in rule.parameters:
            condition &= lengths >= int(rule.parameters["min_length"])
        if "max_length" in rule.parameters:
            condition &= lengths <= int(rule.parameters["max_length"])
        statuses.loc[eligible] = _pass_fail(condition)
        return statuses

    def _domain(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        values = set(str(value) for value in _domain_values(rule.parameters))
        condition = dataframe.loc[eligible, rule.target_column].astype(str).isin(values)
        statuses.loc[eligible] = _pass_fail(condition)
        return statuses

    def _type_check(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        expected_type = str(
            rule.parameters.get("expected_type") or rule.parameters.get("data_type") or rule.parameters.get("value_format")
        ).lower()
        values = dataframe.loc[eligible, rule.target_column]
        if expected_type in NUMERIC_VALUE_FORMATS:
            converted, miscast = _coerce_numeric(values, expected_type)
            statuses.loc[converted.index[miscast]] = "miscast"
            statuses.loc[converted.index[~miscast]] = "passed"
            return statuses
        if expected_type in {"datetime", "date", "timestamp"}:
            converted = pd.to_datetime(values, errors="coerce", utc=True)
            miscast = converted.isna()
            statuses.loc[eligible & statuses.index.to_series().isin(converted.index[miscast])] = "miscast"
            statuses.loc[eligible & statuses.index.to_series().isin(converted.index[~miscast])] = "passed"
            return statuses
        statuses.loc[eligible] = "passed"
        return statuses

    def _range(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        value_format = str(rule.parameters.get("value_format") or rule.parameters.get("expected_type") or "number").lower()
        converted, miscast = _coerce_numeric(dataframe.loc[eligible, rule.target_column], value_format)
        condition = pd.Series(True, index=converted.index)
        if "min_value" in rule.parameters:
            condition &= converted >= float(rule.parameters["min_value"])
        if "max_value" in rule.parameters:
            condition &= converted <= float(rule.parameters["max_value"])
        statuses.loc[converted.index[miscast]] = "miscast"
        statuses.loc[converted.index[~miscast]] = _pass_fail(condition[~miscast])
        return statuses

    def _date_parseable(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        converted = pd.to_datetime(dataframe.loc[eligible, rule.target_column], errors="coerce", utc=True)
        miscast = converted.isna()
        statuses.loc[converted.index[miscast]] = "miscast"
        statuses.loc[converted.index[~miscast]] = "passed"
        return statuses

    def _not_future(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, _, eligible = _initial_statuses(dataframe, rule, rule.target_column)
        converted = pd.to_datetime(dataframe.loc[eligible, rule.target_column], errors="coerce", utc=True)
        miscast = converted.isna()
        now = pd.Timestamp.now(tz=timezone.utc)
        statuses.loc[converted.index[miscast]] = "miscast"
        statuses.loc[converted.index[~miscast]] = _pass_fail(converted[~miscast] <= now)
        return statuses

    def _uniqueness(self, dataframe: pd.DataFrame, dataset_config: DatasetConfig, rule: RuleConfig) -> pd.Series:
        key_columns = _key_columns(rule, dataset_config)
        statuses, in_scope, _ = _initial_statuses(dataframe, rule, None)
        key_empty = pd.Series(False, index=dataframe.index)
        for column in key_columns:
            key_empty |= _is_empty(dataframe[column])
        if rule.null_policy == "ignore":
            statuses.loc[in_scope & key_empty] = "not_applicable"
            eligible = in_scope & ~key_empty
        else:
            statuses.loc[in_scope & key_empty] = "empty"
            eligible = in_scope & ~key_empty
        duplicated = dataframe.loc[eligible, key_columns].duplicated(keep=False)
        statuses.loc[duplicated.index] = _pass_fail(~duplicated)
        return statuses

    def _full_row_duplicate(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        statuses, in_scope, _ = _initial_statuses(dataframe, rule, None)
        duplicated = dataframe.loc[in_scope].duplicated(keep=False)
        statuses.loc[duplicated.index] = _pass_fail(~duplicated)
        return statuses

    def _comparison(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        params = rule.parameters
        left_column = str(params["left_column"])
        right_column = params.get("right_column")
        related_columns = [left_column] + ([str(right_column)] if right_column else [])
        right_expression = params.get("right_expression")
        if isinstance(right_expression, dict):
            related_columns.extend(str(column) for column in right_expression.get("columns", []))
        statuses, in_scope, _ = _initial_statuses(dataframe, rule, None)
        empty = pd.Series(False, index=dataframe.index)
        for column in related_columns:
            empty |= _is_empty(dataframe[column])
        if rule.null_policy == "ignore":
            statuses.loc[in_scope & empty] = "not_applicable"
            eligible = in_scope & ~empty
        else:
            statuses.loc[in_scope & empty] = "empty"
            eligible = in_scope & ~empty

        left_format = str(params.get("left_value_format") or params.get("value_format") or "").lower()
        right_format = str(params.get("right_value_format") or params.get("value_format") or "").lower()
        left = dataframe.loc[eligible, left_column]
        if right_column:
            right: Any = dataframe.loc[eligible, str(right_column)]
        elif isinstance(right_expression, dict):
            right, right_miscast = _evaluate_numeric_expression(dataframe.loc[eligible], right_expression, params)
        else:
            right = params["right_value"]
            right_miscast = pd.Series(False, index=left.index)

        condition, miscast = _compare_values(
            left,
            right,
            str(params.get("operator", "eq")),
            left_format=left_format,
            right_format=right_format,
            tolerance=float(params.get("tolerance", 0)),
        )
        if isinstance(right_expression, dict):
            miscast |= right_miscast
        statuses.loc[miscast.index[miscast]] = "miscast"
        statuses.loc[condition.index[~miscast]] = _pass_fail(condition[~miscast])
        return statuses

    def _conditional_required(self, dataframe: pd.DataFrame, rule: RuleConfig) -> pd.Series:
        required_column = str(rule.parameters.get("required_column") or rule.target_column)
        condition = _scope_mask(dataframe, rule.parameters.get("when") or rule.scope_filter)
        statuses = pd.Series("not_applicable", index=dataframe.index, dtype="object")
        empty = condition & _is_empty(dataframe[required_column])
        if rule.null_policy == "ignore":
            statuses.loc[empty] = "not_applicable"
        else:
            statuses.loc[empty] = "empty"
        statuses.loc[condition & ~empty] = "passed"
        return statuses

    def _freshness(self, dataframe: pd.DataFrame, dataset_config: DatasetConfig, rule: RuleConfig) -> pd.Series:
        timestamp_column = str(rule.parameters.get("timestamp_column") or rule.target_column or dataset_config.timestamp_column)
        max_lag_hours = float(
            rule.parameters.get("max_freshness_lag_hours") or dataset_config.sla_config.get("max_freshness_lag_hours")
        )
        converted = pd.to_datetime(dataframe[timestamp_column], errors="coerce", utc=True)
        if converted.dropna().empty:
            raise ValueError(f"No parseable timestamps found in '{timestamp_column}'")
        lag_hours = (pd.Timestamp.now(tz=timezone.utc) - converted.max()).total_seconds() / 3600
        return pd.Series(["passed" if lag_hours <= max_lag_hours else "failed"])


def _initial_statuses(
    dataframe: pd.DataFrame, rule: RuleConfig, target_column: str | None
) -> tuple[pd.Series, pd.Series, pd.Series]:
    in_scope = _scope_mask(dataframe, rule.scope_filter)
    statuses = pd.Series("not_applicable", index=dataframe.index, dtype="object")
    if target_column is None:
        return statuses, in_scope, in_scope.copy()
    empty = in_scope & _is_empty(dataframe[target_column])
    if rule.null_policy == "ignore":
        statuses.loc[empty] = "not_applicable"
    else:
        statuses.loc[empty] = "empty"
    eligible = in_scope & ~empty
    return statuses, in_scope, eligible


def _scope_mask(dataframe: pd.DataFrame, scope_filter: Any) -> pd.Series:
    if not scope_filter:
        return pd.Series(True, index=dataframe.index)
    column = str(scope_filter["column"])
    operator = str(scope_filter.get("operator", "eq"))
    value = scope_filter.get("value")
    values = scope_filter.get("values", value)
    series = dataframe[column]
    if operator == "eq":
        return series.astype(str) == str(value)
    if operator == "ne":
        return series.astype(str) != str(value)
    if operator == "in":
        return series.astype(str).isin({str(item) for item in values})
    if operator == "not_in":
        return ~series.astype(str).isin({str(item) for item in values})
    comparable = pd.to_numeric(series, errors="coerce")
    expected = float(value)
    if operator == "gt":
        return comparable > expected
    if operator == "gte":
        return comparable >= expected
    if operator == "lt":
        return comparable < expected
    if operator == "lte":
        return comparable <= expected
    raise ValueError(f"Unsupported scope_filter operator '{operator}'")


def _is_empty(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def _pass_fail(condition: pd.Series) -> pd.Series:
    return condition.map(lambda passed: "passed" if bool(passed) else "failed")


def _coerce_numeric(values: Any, value_format: str = "number") -> tuple[pd.Series, pd.Series]:
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    value_format = value_format.lower()
    if value_format in {"currency", "percentage"}:
        cleaned = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
        converted = pd.to_numeric(cleaned, errors="coerce")
    elif value_format in {"integer", "int"}:
        converted = pd.to_numeric(series, errors="coerce")
    else:
        cleaned = series.astype(str).str.replace(",", "", regex=False)
        converted = pd.to_numeric(cleaned, errors="coerce")
    miscast = converted.isna()
    if value_format in {"integer", "int"}:
        miscast |= converted.dropna().mod(1).ne(0).reindex(converted.index, fill_value=False)
    return converted, miscast


def _compare_values(
    left: pd.Series,
    right: Any,
    operator: str,
    *,
    left_format: str = "",
    right_format: str = "",
    tolerance: float = 0,
) -> tuple[pd.Series, pd.Series]:
    use_numeric = operator not in {"eq", "ne"} or left_format in NUMERIC_VALUE_FORMATS or right_format in NUMERIC_VALUE_FORMATS
    if use_numeric:
        left_numeric, left_miscast = _coerce_numeric(left, left_format or "number")
        if isinstance(right, pd.Series):
            right_numeric, right_miscast = _coerce_numeric(right, right_format or "number")
        else:
            right_numeric, right_miscast = _coerce_numeric(pd.Series(right, index=left.index), right_format or "number")
        miscast = left_miscast | right_miscast
        if operator == "eq":
            condition = (left_numeric - right_numeric).abs() <= tolerance
        elif operator == "ne":
            condition = (left_numeric - right_numeric).abs() > tolerance
        elif operator == "gt":
            condition = left_numeric > right_numeric
        elif operator == "gte":
            condition = left_numeric >= right_numeric
        elif operator == "lt":
            condition = left_numeric < right_numeric
        elif operator == "lte":
            condition = left_numeric <= right_numeric
        else:
            raise ValueError(f"Unsupported comparison operator '{operator}'")
        return condition.reindex(left.index, fill_value=False), miscast.reindex(left.index, fill_value=True)

    if operator in {"eq", "ne"}:
        if isinstance(right, pd.Series):
            condition = left.astype(str).eq(right.astype(str))
        else:
            condition = left.astype(str).eq(str(right))
        if operator == "ne":
            condition = ~condition
        return condition, pd.Series(False, index=left.index)
    raise ValueError(f"Unsupported comparison operator '{operator}'")


def _evaluate_numeric_expression(
    dataframe: pd.DataFrame, expression: dict[str, Any], params: dict[str, Any]
) -> tuple[pd.Series, pd.Series]:
    operator = str(expression.get("operator", "multiply"))
    columns = [str(column) for column in expression.get("columns", [])]
    value_formats = params.get("value_formats") if isinstance(params.get("value_formats"), dict) else {}
    if not columns:
        raise ValueError("right_expression requires columns")

    values = []
    miscast = pd.Series(False, index=dataframe.index)
    for column in columns:
        converted, column_miscast = _coerce_numeric(dataframe[column], str(value_formats.get(column, "number")))
        values.append(converted)
        miscast |= column_miscast

    result = values[0]
    for value in values[1:]:
        if operator == "multiply":
            result = result * value
        elif operator == "add":
            result = result + value
        elif operator == "subtract":
            result = result - value
        elif operator == "divide":
            result = result / value
        else:
            raise ValueError(f"Unsupported right_expression operator '{operator}'")
    return result, miscast


def _compare(left: pd.Series, right: Any, operator: str) -> pd.Series:
    if operator in {"eq", "ne"}:
        condition = left.astype(str).eq(right.astype(str) if isinstance(right, pd.Series) else str(right))
        return condition if operator == "eq" else ~condition

    numeric_left = pd.to_numeric(left, errors="coerce")
    numeric_right = pd.to_numeric(right, errors="coerce") if isinstance(right, pd.Series) else float(right)
    if operator == "gt":
        return numeric_left > numeric_right
    if operator == "gte":
        return numeric_left >= numeric_right
    if operator == "lt":
        return numeric_left < numeric_right
    if operator == "lte":
        return numeric_left <= numeric_right
    raise ValueError(f"Unsupported comparison operator '{operator}'")


def _result_from_statuses(
    rule_run_id: str,
    rule: RuleConfig,
    evaluation_unit: str,
    statuses: pd.Series,
    measurement_status: str = "measured",
    error_message: str | None = None,
) -> RuleEvaluationResult:
    counts = statuses.value_counts().to_dict()
    passed = int(counts.get("passed", 0))
    failed = int(counts.get("failed", 0))
    miscast = int(counts.get("miscast", 0))
    empty = int(counts.get("empty", 0))
    not_applicable = int(counts.get("not_applicable", 0))
    return RuleEvaluationResult(
        rule_run_id=rule_run_id,
        rule_id=rule.rule_id,
        dataset_id=rule.dataset_id,
        target_table=rule.target_table,
        target_column=rule.target_column,
        dimension=rule.dimension,
        evaluation_unit=evaluation_unit,
        passed=passed,
        failed=failed,
        miscast=miscast,
        empty=empty,
        not_applicable=not_applicable,
        total_records_in_scope=passed + failed + miscast + empty,
        threshold=rule.threshold,
        measurement_status=measurement_status,
        error_message=error_message,
        evaluated_at=iso(utc_now()) or "",
    )


def not_measured_result(rule_run_id: str, rule: RuleConfig, error_message: str) -> RuleEvaluationResult:
    return _empty_result(rule_run_id, rule, "not_measured", error_message)


def skipped_result(rule_run_id: str, rule: RuleConfig, error_message: str) -> RuleEvaluationResult:
    return _empty_result(rule_run_id, rule, "skipped", error_message)


def _empty_result(rule_run_id: str, rule: RuleConfig, measurement_status: str, error_message: str) -> RuleEvaluationResult:
    return RuleEvaluationResult(
        rule_run_id=rule_run_id,
        rule_id=rule.rule_id,
        dataset_id=rule.dataset_id,
        target_table=rule.target_table,
        target_column=rule.target_column,
        dimension=rule.dimension,
        evaluation_unit="record",
        passed=0,
        failed=0,
        miscast=0,
        empty=0,
        not_applicable=0,
        total_records_in_scope=0,
        threshold=rule.threshold,
        measurement_status=measurement_status,
        error_message=error_message,
        evaluated_at=iso(utc_now()) or "",
    )


def _sample_issues(
    dataframe: pd.DataFrame,
    statuses: pd.Series,
    dataset_config: DatasetConfig,
    rule: RuleConfig,
    rule_run_id: str,
    sample_limit: int,
) -> list[RuleIssueSample]:
    limit = int(rule.parameters.get("issue_sample_limit", sample_limit))
    sampled_at = iso(utc_now()) or ""
    issue_indexes = statuses[statuses.isin(ISSUE_TYPES)].head(limit).index
    samples: list[RuleIssueSample] = []
    for index in issue_indexes:
        target_column = rule.target_column or rule.parameters.get("required_column") or rule.parameters.get("left_column")
        actual_value = _actual_value(dataframe, index, target_column)
        if rule.mask_actual_value or bool(rule.parameters.get("mask_actual_value", False)):
            actual_value = "***MASKED***" if actual_value is not None else None
        samples.append(
            RuleIssueSample(
                rule_run_id=rule_run_id,
                rule_id=rule.rule_id,
                dataset_id=rule.dataset_id,
                record_key=_record_key(dataframe, index, dataset_config),
                target_column=target_column,
                actual_value=actual_value,
                expected_condition=_expected_condition(rule),
                issue_type=str(statuses.loc[index]),
                sampled_at=sampled_at,
            )
        )
    return samples


def _record_key(dataframe: pd.DataFrame, index: Any, dataset_config: DatasetConfig) -> str:
    key_columns = dataset_config.primary_key or dataset_config.composite_key or dataset_config.business_key
    if key_columns and all(column in dataframe.columns for column in key_columns):
        return "|".join(str(dataframe.at[index, column]) for column in key_columns)
    return str(index)


def _actual_value(dataframe: pd.DataFrame, index: Any, target_column: Any) -> str | None:
    if target_column and str(target_column) in dataframe.columns:
        return str(dataframe.at[index, str(target_column)])
    return None


def _expected_condition(rule: RuleConfig) -> str:
    if rule.description:
        return rule.description
    if rule.rule_name:
        return rule.rule_name
    return f"{rule.rule_type} rule {rule.rule_id}"
