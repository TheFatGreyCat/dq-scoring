from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DEFAULT_DIMENSION_WEIGHTS = {
    "Completeness": 0.20,
    "Validity": 0.20,
    "Consistency": 0.15,
    "Timeliness": 0.10,
    "Uniqueness": 0.20,
    "Accuracy Proxy": 0.15,
}

DATASET_TYPES = ["default", "master_data", "transaction", "product_catalog", "reference_data", "log_event"]
SUPPORTED_TYPES = ["string", "integer", "numeric", "datetime"]
TYPE_CHECK_TYPES = {"integer", "numeric"}


@dataclass(frozen=True)
class OnboardingArtifacts:
    dataset_config_path: Path
    rules_config_path: Path
    scoring_config_path: Path
    sample_path: Path


def sanitize_dataset_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        raise ValueError("dataset_id is required")
    if not re.match(r"^[a-z][a-z0-9_]*$", normalized):
        raise ValueError("dataset_id must start with a letter and contain only lowercase letters, numbers, and underscores")
    return normalized


def load_csv_bytes(content: bytes) -> pd.DataFrame:
    dataframe = pd.read_csv(BytesIO(content), keep_default_na=False)
    if dataframe.empty or len(dataframe.columns) == 0:
        raise ValueError("Uploaded CSV must contain at least one column and one row")
    return dataframe


def infer_schema(dataframe: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        str(column): {
            "data_type": _infer_column_type(str(column), dataframe[column]),
            "nullable": bool(_is_empty(dataframe[column]).any()),
        }
        for column in dataframe.columns
    }


def schema_to_rows(schema: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "column_name": column,
            "data_type": metadata.get("data_type", "string"),
            "nullable": bool(metadata.get("nullable", True)),
        }
        for column, metadata in schema.items()
    ]


def rows_to_schema(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    schema: dict[str, dict[str, Any]] = {}
    for row in rows:
        column = str(row.get("column_name", "")).strip()
        if not column:
            continue
        data_type = str(row.get("data_type") or "string")
        if data_type not in SUPPORTED_TYPES:
            data_type = "string"
        schema[column] = {
            "data_type": data_type,
            "nullable": bool(row.get("nullable", True)),
        }
    if not schema:
        raise ValueError("At least one schema column is required")
    return schema


def default_mandatory_fields(dataframe: pd.DataFrame) -> list[str]:
    fields = [str(column) for column in dataframe.columns if not _is_empty(dataframe[column]).any()]
    return fields[: min(len(fields), 10)]


def default_cde_fields(dataframe: pd.DataFrame, mandatory_fields: list[str]) -> list[str]:
    preferred = [
        column
        for column in dataframe.columns
        if any(token in str(column).lower() for token in ("id", "date", "amount", "price", "email", "phone", "status"))
    ]
    values = list(dict.fromkeys([str(column) for column in preferred] + mandatory_fields))
    return values[: min(len(values), 12)]


def build_dataset_config(
    *,
    dataset_id: str,
    dataset_name: str,
    dataset_type: str,
    storage_path: str,
    declared_schema: dict[str, dict[str, Any]],
    primary_key: list[str] | None = None,
    business_key: list[str] | None = None,
    mandatory_fields: list[str] | None = None,
    cde_fields: list[str] | None = None,
    timestamp_column: str | None = None,
    max_freshness_lag_hours: int | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name or dataset_id,
        "dataset_type": dataset_type or "default",
        "source_type": "csv",
        "storage_path": storage_path,
        "declared_schema": declared_schema,
        "mandatory_fields": mandatory_fields or [],
        "cde_fields": cde_fields or [],
        "profiling_config": {
            "execution_mode": "gx_pandas",
            "sampling_method": "full_scan",
            "random_seed": 42,
            "enable_pattern_detection": True,
            "enable_candidate_rule_generation": True,
            "enable_basic_anomaly_detection": True,
            "thresholds": {
                "not_null_max_null_ratio": 0.05,
                "unique_min_ratio": 0.95,
                "pattern_min_ratio": 0.8,
                "domain_max_distinct": 50,
                "domain_max_uniqueness_ratio": 0.2,
                "volume_deviation": 0.3,
            },
        },
    }
    if primary_key:
        config["primary_key"] = primary_key
    if business_key:
        config["business_key"] = business_key
    if timestamp_column:
        config["timestamp_column"] = timestamp_column
        config["freshness_time_basis"] = timestamp_column
        if max_freshness_lag_hours:
            config["sla_config"] = {
                "expected_frequency": "daily",
                "max_freshness_lag_hours": int(max_freshness_lag_hours),
            }
    return config


def generate_rules(
    *,
    dataset_id: str,
    declared_schema: dict[str, dict[str, Any]],
    mandatory_fields: list[str],
    primary_key: list[str] | None = None,
    business_key: list[str] | None = None,
    timestamp_column: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []
    for column in mandatory_fields:
        rules.append(
            _rule(
                dataset_id,
                "COMP",
                column,
                "Completeness",
                "not_blank",
                target_column=column,
                threshold=99,
                null_policy="fail",
                severity="high",
                description=f"{column} must contain a value",
            )
        )

    for column, metadata in declared_schema.items():
        data_type = str(metadata.get("data_type", "string"))
        if data_type in TYPE_CHECK_TYPES:
            rules.append(
                _rule(
                    dataset_id,
                    "VALI",
                    f"{column}_type",
                    "Validity",
                    "type_check",
                    target_column=column,
                    parameters={"expected_type": "integer" if data_type == "integer" else "numeric"},
                    threshold=98,
                    severity="medium",
                    description=f"{column} must parse as {data_type}",
                )
            )
        elif data_type == "datetime":
            rules.append(
                _rule(
                    dataset_id,
                    "VALI",
                    f"{column}_date",
                    "Validity",
                    "date_parseable",
                    target_column=column,
                    threshold=98,
                    severity="medium",
                    description=f"{column} must parse as a date/time value",
                )
            )

        range_params = _range_parameters(column, data_type)
        if range_params:
            rules.append(
                _rule(
                    dataset_id,
                    "ACCU",
                    f"{column}_range",
                    "Accuracy Proxy",
                    "plausibility_range",
                    target_column=column,
                    parameters=range_params,
                    threshold=95,
                    severity="medium",
                    description=f"{column} must fall within a plausible range",
                )
            )

    key_columns = primary_key or business_key or []
    if key_columns:
        rules.append(
            _rule(
                dataset_id,
                "UNIQ",
                "key",
                "Uniqueness",
                "uniqueness",
                target_column=key_columns[0],
                parameters={"key_columns": key_columns},
                threshold=99,
                null_policy="ignore",
                severity="critical",
                description="Configured key columns must be unique",
            )
        )

    rules.append(
        _rule(
            dataset_id,
            "UNIQ",
            "duprow",
            "Uniqueness",
            "full_row_duplicate",
            threshold=99,
            null_policy="ignore",
            severity="medium",
            description="Full dataset rows must not be duplicated",
        )
    )

    if timestamp_column:
        rules.append(
            _rule(
                dataset_id,
                "TIME",
                f"{timestamp_column}_not_future",
                "Timeliness",
                "not_future",
                target_column=timestamp_column,
                threshold=99,
                null_policy="ignore",
                severity="medium",
                description=f"{timestamp_column} must not be future dated",
            )
        )

    return {"rules": rules}


def generate_scoring_config(dataset_type: str) -> dict[str, Any]:
    return {
        "dataset_type": dataset_type or "default",
        "dimension_weights": DEFAULT_DIMENSION_WEIGHTS,
        "warning_margin": 3,
        "quality_gate_pass_threshold": 80,
        "quality_gate_warning_threshold": 65,
    }


def persist_onboarding_artifacts(
    *,
    root: str | Path,
    dataset_id: str,
    dataset_name: str,
    dataset_type: str,
    csv_content: bytes,
    declared_schema: dict[str, dict[str, Any]],
    primary_key: list[str] | None,
    business_key: list[str] | None,
    mandatory_fields: list[str],
    cde_fields: list[str],
    timestamp_column: str | None,
    max_freshness_lag_hours: int | None,
) -> OnboardingArtifacts:
    base = Path(root)
    sample_path = base / "data" / "samples" / f"{dataset_id}.csv"
    dataset_config_path = base / "data" / "configs" / f"{dataset_id}.yaml"
    rules_config_path = base / "data" / "rules" / f"{dataset_id}_rules.yaml"
    scoring_config_path = base / "data" / "scoring" / f"{dataset_id}_scoring.yaml"

    for path in (sample_path, dataset_config_path, rules_config_path, scoring_config_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    sample_path.write_bytes(csv_content)
    storage_path = _repo_relative(sample_path, base)
    dataset_config = build_dataset_config(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        dataset_type=dataset_type,
        storage_path=storage_path,
        declared_schema=declared_schema,
        primary_key=primary_key,
        business_key=business_key,
        mandatory_fields=mandatory_fields,
        cde_fields=cde_fields,
        timestamp_column=timestamp_column,
        max_freshness_lag_hours=max_freshness_lag_hours,
    )
    rules = generate_rules(
        dataset_id=dataset_id,
        declared_schema=declared_schema,
        mandatory_fields=mandatory_fields,
        primary_key=primary_key,
        business_key=business_key,
        timestamp_column=timestamp_column,
    )
    scoring_config = generate_scoring_config(dataset_type)

    _write_yaml(dataset_config_path, dataset_config)
    _write_yaml(rules_config_path, rules)
    _write_yaml(scoring_config_path, scoring_config)

    return OnboardingArtifacts(
        dataset_config_path=dataset_config_path,
        rules_config_path=rules_config_path,
        scoring_config_path=scoring_config_path,
        sample_path=sample_path,
    )


def artifact_paths_for_dataset(root: str | Path, dataset_id: str) -> OnboardingArtifacts:
    base = Path(root)
    return OnboardingArtifacts(
        dataset_config_path=base / "data" / "configs" / f"{dataset_id}.yaml",
        rules_config_path=base / "data" / "rules" / f"{dataset_id}_rules.yaml",
        scoring_config_path=base / "data" / "scoring" / f"{dataset_id}_scoring.yaml",
        sample_path=base / "data" / "samples" / f"{dataset_id}.csv",
    )


def artifact_summary(artifacts: OnboardingArtifacts) -> dict[str, str]:
    return {
        "dataset_config": str(artifacts.dataset_config_path),
        "rules_config": str(artifacts.rules_config_path),
        "scoring_config": str(artifacts.scoring_config_path),
        "sample": str(artifacts.sample_path),
    }


def _rule(
    dataset_id: str,
    family: str,
    suffix: str,
    dimension: str,
    rule_type: str,
    *,
    target_column: str | None = None,
    parameters: dict[str, Any] | None = None,
    threshold: float = 98,
    null_policy: str = "ignore",
    severity: str = "medium",
    description: str | None = None,
) -> dict[str, Any]:
    rule_suffix = re.sub(r"[^A-Za-z0-9]+", "_", suffix).strip("_").upper()
    rule_id = f"DQ-{family}-{dataset_id.upper()}-{rule_suffix}-001"
    rule = {
        "rule_id": rule_id,
        "rule_name": description or f"{dimension} {rule_type} check",
        "description": description or f"{dimension} {rule_type} check",
        "dataset_id": dataset_id,
        "dimension": dimension,
        "rule_type": rule_type,
        "parameters": parameters or {},
        "null_policy": null_policy,
        "threshold": threshold,
        "severity": severity,
        "execution_backend": "pandas",
        "status": "active",
        "score_enabled": True,
    }
    if target_column:
        rule["target_column"] = target_column
    return rule


def _infer_column_type(column_name: str, series: pd.Series) -> str:
    non_empty = series[~_is_empty(series)]
    if non_empty.empty:
        return "string"
    if pd.api.types.is_integer_dtype(non_empty):
        return "integer"
    if pd.api.types.is_numeric_dtype(non_empty):
        return "numeric"

    numeric = _coerce_numeric(non_empty)
    numeric_ratio = numeric.notna().mean()
    lower = column_name.lower()
    id_like = lower.endswith("id") or lower.endswith("_id") or lower == "id"
    if numeric_ratio >= 0.95 and not id_like:
        return "integer" if numeric.dropna().mod(1).eq(0).all() else "numeric"

    date_like_name = any(token in lower for token in ("date", "time", "timestamp", "updated_at"))
    if date_like_name:
        parsed = pd.to_datetime(non_empty, errors="coerce", utc=True)
        if parsed.notna().mean() >= 0.80:
            return "datetime"
    return "string"


def _range_parameters(column_name: str, data_type: str) -> dict[str, Any] | None:
    if data_type not in TYPE_CHECK_TYPES:
        return None
    lower = column_name.lower()
    params: dict[str, Any] = {"value_format": "numeric"}
    if "age" in lower:
        params.update({"min_value": 0, "max_value": 120})
    elif "rating" in lower or "score" in lower:
        params.update({"min_value": 0, "max_value": 5})
    elif "percent" in lower or "percentage" in lower or lower.endswith("_pct"):
        params.update({"min_value": 0, "max_value": 100})
    elif any(token in lower for token in ("amount", "price", "cost", "quantity", "qty", "count", "total")):
        params.update({"min_value": 0})
    else:
        return None
    return params


def _is_empty(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def _coerce_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _repo_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")


def to_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
