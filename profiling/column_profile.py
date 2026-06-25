from __future__ import annotations

import math
import re
import warnings
from collections import Counter
from typing import Any

import pandas as pd

from profiling.models import ColumnProfile, DatasetConfig

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def profile_columns(df: pd.DataFrame, config: DatasetConfig, run_id: str | None = None) -> list[ColumnProfile]:
    run_id = run_id or "RUN_PREVIEW"
    return [_profile_column(df[column], config, run_id) for column in df.columns]


def _profile_column(series: pd.Series, config: DatasetConfig, run_id: str) -> ColumnProfile:
    total = len(series)
    column = str(series.name)
    schema = config.declared_schema.get(column, {})
    declared_type = schema.get("data_type")
    null_count = int(series.isna().sum())
    blank_count = int(series.astype("string").str.strip().eq("").fillna(False).sum())
    non_empty = series[~(series.isna() | series.astype("string").str.strip().eq("").fillna(False))]
    distinct_count = int(non_empty.nunique(dropna=True))
    denominator = len(non_empty) if len(non_empty) else total
    uniqueness_ratio = _ratio(distinct_count, denominator)
    inferred_type = _infer_type(non_empty)
    miscast_count = _count_miscast(non_empty, declared_type)

    numeric = pd.to_numeric(non_empty, errors="coerce")
    numeric_valid = numeric.dropna()
    datetimes = _to_datetime(non_empty)
    datetime_valid = datetimes.dropna()

    min_value = max_value = None
    mean_value = std_value = p25 = p50 = p75 = p99 = None
    if inferred_type == "numeric" and len(numeric_valid):
        min_value = _safe_string(numeric_valid.min())
        max_value = _safe_string(numeric_valid.max())
        mean_value = _finite(numeric_valid.mean())
        std_value = _finite(numeric_valid.std(ddof=0))
        p25 = _finite(numeric_valid.quantile(0.25))
        p50 = _finite(numeric_valid.quantile(0.50))
        p75 = _finite(numeric_valid.quantile(0.75))
        p99 = _finite(numeric_valid.quantile(0.99))
    elif inferred_type == "datetime" and len(datetime_valid):
        min_value = _safe_string(datetime_valid.min())
        max_value = _safe_string(datetime_valid.max())
    elif len(non_empty):
        min_value = _safe_string(non_empty.min())
        max_value = _safe_string(non_empty.max())

    return ColumnProfile(
        run_id=run_id,
        dataset_id=config.dataset_id,
        column_name=column,
        declared_data_type=declared_type,
        inferred_data_type=inferred_type,
        null_count=null_count,
        null_ratio=_ratio(null_count, total),
        blank_count=blank_count,
        distinct_count=distinct_count,
        uniqueness_ratio=uniqueness_ratio,
        min_value=min_value,
        max_value=max_value,
        mean_value=mean_value,
        std_value=std_value,
        p25=p25,
        p50=p50,
        p75=p75,
        p99=p99,
        top_values=_top_values(non_empty),
        pattern_frequency=_pattern_frequency(non_empty) if config.profiling_config.enable_pattern_detection else {},
        length_distribution=_length_distribution(non_empty),
        miscast_count=miscast_count,
    )


def _infer_type(series: pd.Series) -> str:
    if len(series) == 0:
        return "unknown"
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.9:
        return "numeric"
    datetimes = _to_datetime(series)
    if datetimes.notna().mean() >= 0.9:
        return "datetime"
    lowered = series.astype(str).str.lower()
    if lowered.isin({"true", "false", "0", "1", "yes", "no"}).mean() >= 0.9:
        return "boolean"
    return "string"


def _count_miscast(series: pd.Series, declared_type: Any) -> int:
    if not declared_type or len(series) == 0:
        return 0
    normalized = str(declared_type).lower()
    if normalized in {"int", "integer", "float", "double", "number", "numeric", "decimal"}:
        return int(pd.to_numeric(series, errors="coerce").isna().sum())
    if normalized in {"date", "datetime", "timestamp"}:
        return int(_to_datetime(series).isna().sum())
    if normalized in {"bool", "boolean"}:
        valid = series.astype(str).str.lower().isin({"true", "false", "0", "1", "yes", "no"})
        return int((~valid).sum())
    return 0


def _to_datetime(series: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(series, errors="coerce")


def _top_values(series: pd.Series) -> dict[str, float]:
    total = len(series)
    return {str(k): _ratio(v, total) for k, v in series.value_counts(dropna=True).head(10).items()}


def _pattern_frequency(series: pd.Series) -> dict[str, float]:
    total = len(series)
    counts: Counter[str] = Counter()
    for value in series.astype(str):
        if EMAIL_RE.match(value):
            counts["valid_email_format"] += 1
        else:
            counts[_shape(value)] += 1
    return {pattern: _ratio(count, total) for pattern, count in counts.most_common(10)}


def _length_distribution(series: pd.Series) -> dict[str, float]:
    total = len(series)
    counts = series.astype(str).str.len().value_counts().sort_index()
    return {str(k): _ratio(v, total) for k, v in counts.items()}


def _shape(value: str) -> str:
    chars = []
    for char in value:
        if char.isalpha():
            chars.append("A")
        elif char.isdigit():
            chars.append("9")
        elif char.isspace():
            chars.append(" ")
        else:
            chars.append(char)
    return "".join(chars)


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _finite(value: Any) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _safe_string(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return str(value)
