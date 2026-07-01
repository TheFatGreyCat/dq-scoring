from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from profiling.models import DatasetConfig

from rules_engine.models import RuleConfig

VALID_DIMENSIONS = {
    "Accuracy",
    "Accuracy Proxy",
    "Completeness",
    "Consistency",
    "Timeliness",
    "Uniqueness",
    "Validity",
}
VALID_RULE_TYPES = {
    "comparison",
    "composite_uniqueness",
    "conditional_required",
    "date_parseable",
    "domain",
    "freshness",
    "full_row_duplicate",
    "length",
    "not_blank",
    "not_future",
    "not_null",
    "plausibility_range",
    "range",
    "regex",
    "type_check",
    "uniqueness",
}
VALID_NULL_POLICIES = {"fail", "ignore"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_EXECUTION_BACKENDS = {"pandas", "gx", "gx_pandas"}
VALID_RULE_STATUSES = {"draft", "active", "inactive", "deprecated"}
VALID_VALUE_FORMATS = {"number", "numeric", "float", "integer", "int", "currency", "percentage"}
VALID_COMPARISON_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte"}
VALID_EXPRESSION_OPERATORS = {"multiply", "add", "subtract", "divide"}


def load_rules(path: str | Path) -> list[RuleConfig]:
    raw = _load_mapping(Path(path))
    return parse_rules(raw)


def parse_rules(raw: dict[str, Any]) -> list[RuleConfig]:
    items = raw.get("rules")
    if not isinstance(items, list):
        raise ValueError("Rule config file must contain a 'rules' list")
    return [parse_rule_config(item) for item in items]


def parse_rule_config(raw: dict[str, Any]) -> RuleConfig:
    if not isinstance(raw, dict):
        raise ValueError("Each rule config entry must be a mapping")
    missing = [field for field in ("rule_id", "dataset_id", "rule_type", "status", "score_enabled") if field not in raw]
    if missing:
        raise ValueError(f"Missing required rule field(s): {', '.join(missing)}")

    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError("Rule field 'parameters' must be a mapping when provided")

    return RuleConfig(
        rule_id=str(raw["rule_id"]),
        rule_name=raw.get("rule_name"),
        description=raw.get("description"),
        dataset_id=str(raw["dataset_id"]),
        target_table=raw.get("target_table"),
        target_column=raw.get("target_column"),
        dimension=raw.get("dimension"),
        rule_type=str(raw["rule_type"]),
        scope_filter=raw.get("scope_filter"),
        parameters=parameters,
        null_policy=str(raw.get("null_policy", "ignore")),
        threshold=_optional_float(raw.get("threshold")),
        severity=str(raw.get("severity", "medium")),
        execution_backend=str(raw.get("execution_backend", "pandas")),
        status=str(raw["status"]),
        score_enabled=bool(raw["score_enabled"]),
        created_by=raw.get("created_by"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        mask_actual_value=bool(raw.get("mask_actual_value", False)),
    )


def validate_rule_config(rule: RuleConfig, dataset_config: DatasetConfig, columns: set[str]) -> list[str]:
    errors: list[str] = []
    if rule.dataset_id != dataset_config.dataset_id:
        errors.append(f"Rule dataset_id '{rule.dataset_id}' does not match dataset '{dataset_config.dataset_id}'")
    if rule.status not in VALID_RULE_STATUSES:
        errors.append(f"Unsupported rule status '{rule.status}'")
    if rule.score_enabled and not rule.dimension:
        errors.append("score_enabled rule must define dimension")
    if rule.score_enabled and rule.threshold is None:
        errors.append("score_enabled rule must define threshold")
    if rule.dimension and rule.dimension not in VALID_DIMENSIONS:
        errors.append(f"Unsupported dimension '{rule.dimension}'")
    if rule.rule_type not in VALID_RULE_TYPES:
        errors.append(f"Unsupported rule_type '{rule.rule_type}'")
    if rule.null_policy not in VALID_NULL_POLICIES:
        errors.append(f"Unsupported null_policy '{rule.null_policy}'")
    if rule.severity not in VALID_SEVERITIES:
        errors.append(f"Unsupported severity '{rule.severity}'")
    if rule.execution_backend not in VALID_EXECUTION_BACKENDS:
        errors.append(f"Unsupported execution_backend '{rule.execution_backend}'")

    target_required = {
        "date_parseable",
        "domain",
        "length",
        "not_blank",
        "not_future",
        "not_null",
        "plausibility_range",
        "range",
        "regex",
        "type_check",
    }
    if rule.rule_type in target_required and not rule.target_column:
        errors.append(f"rule_type '{rule.rule_type}' requires target_column")
    if rule.target_column and rule.target_column not in columns:
        errors.append(f"target_column '{rule.target_column}' does not exist in dataset")

    errors.extend(_validate_scope_filter(rule.scope_filter, columns))
    errors.extend(_validate_parameters(rule, dataset_config, columns))
    errors.extend(_validate_value_formats(rule.parameters))
    return errors


def _validate_parameters(rule: RuleConfig, dataset_config: DatasetConfig, columns: set[str]) -> list[str]:
    params = rule.parameters
    errors: list[str] = []
    if rule.rule_type == "regex" and not params.get("pattern"):
        errors.append("regex rule requires parameters.pattern")
    if rule.rule_type == "length" and not any(key in params for key in ("exact_length", "min_length", "max_length")):
        errors.append("length rule requires exact_length, min_length, or max_length")
    if rule.rule_type == "domain" and not _domain_values(params):
        errors.append("domain rule requires parameters.values or parameters.domain_values")
    if rule.rule_type == "type_check" and not (params.get("expected_type") or params.get("data_type") or params.get("value_format")):
        errors.append("type_check rule requires parameters.expected_type, parameters.data_type, or parameters.value_format")
    if rule.rule_type in {"range", "plausibility_range"} and not any(key in params for key in ("min_value", "max_value")):
        errors.append(f"{rule.rule_type} rule requires min_value or max_value")
    if rule.rule_type in {"uniqueness", "composite_uniqueness"}:
        key_columns = _key_columns(rule, dataset_config)
        if not key_columns:
            errors.append(f"{rule.rule_type} rule requires target_column or parameters.key_columns")
        errors.extend(_missing_columns(key_columns, columns, "key column"))
    if rule.rule_type == "freshness":
        timestamp_column = str(params.get("timestamp_column") or rule.target_column or dataset_config.timestamp_column or "")
        if not timestamp_column:
            errors.append("freshness rule requires target_column, parameters.timestamp_column, or dataset timestamp_column")
        elif timestamp_column not in columns:
            errors.append(f"timestamp_column '{timestamp_column}' does not exist in dataset")
        if not (params.get("max_freshness_lag_hours") or dataset_config.sla_config.get("max_freshness_lag_hours")):
            errors.append("freshness rule requires max_freshness_lag_hours in parameters or dataset sla_config")
    if rule.rule_type == "comparison":
        left = params.get("left_column")
        right_column = params.get("right_column")
        right_expression = params.get("right_expression")
        if not left:
            errors.append("comparison rule requires parameters.left_column")
        if not right_column and "right_value" not in params and not right_expression:
            errors.append("comparison rule requires parameters.right_column, parameters.right_value, or parameters.right_expression")
        if str(params.get("operator", "eq")) not in VALID_COMPARISON_OPERATORS:
            errors.append(f"Unsupported comparison operator '{params.get('operator')}'")
        errors.extend(_missing_columns([item for item in (left, right_column) if item], columns, "comparison column"))
        if right_expression is not None:
            errors.extend(_validate_right_expression(right_expression, columns))
    if rule.rule_type == "conditional_required":
        required = str(params.get("required_column") or rule.target_column or "")
        if not required:
            errors.append("conditional_required rule requires target_column or parameters.required_column")
        elif required not in columns:
            errors.append(f"required_column '{required}' does not exist in dataset")
        when = params.get("when") or rule.scope_filter
        if not when:
            errors.append("conditional_required rule requires parameters.when or scope_filter")
        else:
            errors.extend(_validate_scope_filter(when, columns))
    return errors


def _validate_value_formats(params: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("value_format", "left_value_format", "right_value_format"):
        if key in params and str(params[key]) not in VALID_VALUE_FORMATS:
            errors.append(f"Unsupported {key} '{params[key]}'")
    value_formats = params.get("value_formats")
    if isinstance(value_formats, dict):
        for column, value_format in value_formats.items():
            if str(value_format) not in VALID_VALUE_FORMATS:
                errors.append(f"Unsupported value_formats.{column} '{value_format}'")
    return errors


def _validate_right_expression(expression: Any, columns: set[str]) -> list[str]:
    if not isinstance(expression, dict):
        return ["right_expression must be a mapping"]
    operator = str(expression.get("operator", "multiply"))
    if operator not in VALID_EXPRESSION_OPERATORS:
        return [f"Unsupported right_expression operator '{operator}'"]
    expression_columns = expression.get("columns")
    if not isinstance(expression_columns, list) or not expression_columns:
        return ["right_expression requires a non-empty columns list"]
    return _missing_columns(expression_columns, columns, "right_expression column")


def _validate_scope_filter(scope_filter: Any, columns: set[str]) -> list[str]:
    if scope_filter is None:
        return []
    if not isinstance(scope_filter, dict):
        return ["scope_filter must be a mapping"]
    column = scope_filter.get("column")
    if not column:
        return ["scope_filter requires column"]
    if str(column) not in columns:
        return [f"scope_filter column '{column}' does not exist in dataset"]
    operator = str(scope_filter.get("operator", "eq"))
    if operator not in {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte"}:
        return [f"Unsupported scope_filter operator '{operator}'"]
    return []


def _domain_values(params: dict[str, Any]) -> list[Any]:
    values = params.get("values", params.get("domain_values"))
    return values if isinstance(values, list) else []


def _key_columns(rule: RuleConfig, dataset_config: DatasetConfig) -> list[str]:
    values = rule.parameters.get("key_columns")
    if isinstance(values, list):
        return [str(value) for value in values]
    if rule.target_column:
        return [rule.target_column]
    if rule.rule_type == "composite_uniqueness":
        return dataset_config.composite_key or dataset_config.business_key
    return dataset_config.primary_key or dataset_config.business_key


def _missing_columns(values: list[Any], columns: set[str], label: str) -> list[str]:
    return [f"{label} '{value}' does not exist in dataset" for value in values if str(value) not in columns]


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        except ModuleNotFoundError:
            data = _parse_simple_yaml(text)
    if not isinstance(data, dict):
        raise ValueError("Rule config file must contain a mapping object")
    return data


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index
        if lines[index][1].startswith("- "):
            values = []
            while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
                item_text = lines[index][1][2:].strip()
                index += 1
                if ":" in item_text:
                    key, _, value = item_text.partition(":")
                    item: dict[str, Any] = {key.strip(): _parse_scalar(value.strip()) if value.strip() else None}
                    if index < len(lines) and lines[index][0] > indent:
                        child, index = parse_block(index, lines[index][0])
                        if isinstance(child, dict):
                            item.update(child)
                    values.append(item)
                else:
                    values.append(_parse_scalar(item_text))
            return values, index

        values: dict[str, Any] = {}
        while index < len(lines) and lines[index][0] == indent and not lines[index][1].startswith("- "):
            key, sep, value = lines[index][1].partition(":")
            if not sep:
                raise ValueError(f"Invalid YAML line: {lines[index][1]}")
            key = key.strip()
            value = value.strip()
            index += 1
            if value:
                values[key] = _parse_scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                values[key], index = parse_block(index, lines[index][0])
            else:
                values[key] = None
        return values, index

    if not lines:
        return {}
    parsed, next_index = parse_block(0, lines[0][0])
    if next_index != len(lines) or not isinstance(parsed, dict):
        raise ValueError("Unsupported YAML structure; install PyYAML for full YAML support")
    return parsed


def _parse_scalar(value: str) -> Any:
    if value == "{}":
        return {}
    if value == "[]":
        return []
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        parsed = value[1:-1]
        if value.startswith('"'):
            parsed = parsed.replace("\\\\", "\\").replace('\\"', '"')
        return parsed
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
