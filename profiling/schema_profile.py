from __future__ import annotations

import pandas as pd

from profiling.models import DatasetConfig, SchemaProfile


def profile_schema(df: pd.DataFrame, config: DatasetConfig) -> SchemaProfile:
    declared = config.declared_schema
    actual_columns = set(df.columns)
    declared_columns = set(declared)

    missing = sorted(declared_columns - actual_columns)
    extra = sorted(actual_columns - declared_columns) if declared else []
    type_mismatches: list[dict[str, str]] = []
    nullable_mismatches: list[dict[str, str]] = []

    for column in sorted(declared_columns & actual_columns):
        declared_type = str(declared[column].get("data_type", "")).lower()
        actual_type = _pandas_type(df[column])
        if declared_type and not _types_compatible(declared_type, actual_type):
            type_mismatches.append(
                {"column_name": column, "declared_data_type": declared_type, "actual_data_type": actual_type}
            )
        nullable = declared[column].get("nullable")
        if nullable is False and df[column].isna().any():
            nullable_mismatches.append({"column_name": column, "declared_nullable": "false", "actual_has_null": "true"})

    for column in config.mandatory_fields:
        if column in actual_columns and _blank_or_null(df[column]).any():
            nullable_mismatches.append({"column_name": column, "declared_nullable": "false", "actual_has_null": "true"})

    return SchemaProfile(missing, extra, type_mismatches, nullable_mismatches)


def _pandas_type(series: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "numeric"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def _types_compatible(declared: str, actual: str) -> bool:
    aliases = {
        "int": "integer",
        "integer": "integer",
        "float": "numeric",
        "double": "numeric",
        "number": "numeric",
        "numeric": "numeric",
        "decimal": "numeric",
        "date": "datetime",
        "datetime": "datetime",
        "timestamp": "datetime",
        "str": "string",
        "string": "string",
        "text": "string",
        "bool": "boolean",
        "boolean": "boolean",
    }
    declared_norm = aliases.get(declared, declared)
    return declared_norm == actual or (declared_norm == "numeric" and actual == "integer")


def _blank_or_null(series: pd.Series) -> pd.Series:
    blank = series.astype("string").str.strip().eq("").fillna(False)
    return series.isna() | blank
