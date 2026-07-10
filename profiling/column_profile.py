from __future__ import annotations

import math
import re
import warnings
from collections import Counter
from typing import Any

import pandas as pd

from profiling.models import ColumnProfile, DatasetConfig

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
TOP_K_VALUES = 10
TOP_VALUE_MAX_LENGTH = 100
PATTERN_TOP_K = 5
MISCAST_EXAMPLE_LIMIT = 5


def profile_columns(df: pd.DataFrame, config: DatasetConfig, run_id: str | None = None, metric_scope: str = "full") -> list[ColumnProfile]:
    run_id = run_id or "RUN_PREVIEW"
    return [_profile_column(df[column], config, run_id, metric_scope) for column in df.columns]


def _profile_column(series: pd.Series, config: DatasetConfig, run_id: str, metric_scope: str) -> ColumnProfile:
    total = len(series)
    column = str(series.name)
    schema = config.declared_schema.get(column, {})
    declared_type = schema.get("data_type")
    null_mask = series.isna()
    blank_mask = _blank_mask(series, null_mask)
    non_null = series[~null_mask]
    non_empty = series[~(null_mask | blank_mask)]
    null_count = int(null_mask.sum())
    blank_count = int(blank_mask.sum())
    non_null_count = int((~null_mask).sum())
    distinct_excluding_null = int(non_empty.nunique(dropna=True))
    distinct_including_null = int(series.astype("string").fillna("<NULL>").nunique(dropna=False)) if total else 0
    uniqueness_ratio = _ratio_or_none(distinct_excluding_null, len(non_empty))
    inferred_type, type_confidence, type_evidence = _infer_type(non_empty)
    miscast_mask = _miscast_mask(non_empty, declared_type or inferred_type)
    miscast_count = int(miscast_mask.sum())

    numeric = _to_numeric(non_empty)
    numeric_valid = numeric.dropna()
    datetimes = _to_datetime(non_empty)
    datetime_valid = datetimes.dropna()

    min_value = max_value = None
    mean_value = std_value = p25 = p50 = p75 = p99 = None
    numeric_summary: dict[str, Any] = {}
    if inferred_type in {"integer", "float", "numeric_string", "integer_like_string"} and len(numeric_valid):
        min_value = _safe_string(numeric_valid.min())
        max_value = _safe_string(numeric_valid.max())
        mean_value = _finite(numeric_valid.mean())
        std_value = _finite(numeric_valid.std(ddof=0))
        p25 = _finite(numeric_valid.quantile(0.25))
        p50 = _finite(numeric_valid.quantile(0.50))
        p75 = _finite(numeric_valid.quantile(0.75))
        p99 = _finite(numeric_valid.quantile(0.99))
        numeric_summary = _numeric_summary(numeric_valid)
    elif inferred_type in {"datetime", "date"} and len(datetime_valid):
        min_value = _safe_string(datetime_valid.min())
        max_value = _safe_string(datetime_valid.max())
    elif len(non_empty):
        min_value = _safe_string(non_empty.min())
        max_value = _safe_string(non_empty.max())

    pattern_frequency = _pattern_frequency(non_empty) if config.profiling_config.enable_pattern_detection else {}
    length_summary = _length_summary(non_empty)
    return ColumnProfile(
        run_id=run_id,
        dataset_id=config.dataset_id,
        column_name=column,
        declared_data_type=declared_type,
        inferred_data_type=inferred_type,
        null_count=null_count,
        null_ratio=_ratio(null_count, total),
        blank_count=blank_count,
        distinct_count=distinct_excluding_null,
        uniqueness_ratio=uniqueness_ratio,
        metric_scope=metric_scope,
        non_null_count=non_null_count,
        distinct_count_including_null=distinct_including_null,
        trimmed_blank_count=blank_count,
        miscast_ratio=_ratio(miscast_count, len(non_empty)),
        inferred_type_confidence=type_confidence,
        inferred_type_evidence=type_evidence,
        top_values_detail=_top_values_detail(non_null, null_count, blank_count),
        patterns_detail=_patterns_detail(pattern_frequency, non_empty),
        length_summary=length_summary,
        numeric_summary=numeric_summary,
        miscast_examples=_miscast_examples(non_empty, miscast_mask),
        min_value=min_value,
        max_value=max_value,
        mean_value=mean_value,
        std_value=std_value,
        p25=p25,
        p50=p50,
        p75=p75,
        p99=p99,
        top_values=_top_values(non_empty),
        pattern_frequency=pattern_frequency,
        length_distribution=_length_distribution(non_empty),
        miscast_count=miscast_count,
    )


def _blank_mask(series: pd.Series, null_mask: pd.Series) -> pd.Series:
    return (~null_mask) & series.astype("string").str.strip().eq("").fillna(False)


def _infer_type(series: pd.Series) -> tuple[str, float, dict[str, Any]]:
    if len(series) == 0:
        return "unknown", 0.0, {"reason": "no non-empty values"}
    as_string = series.astype(str)
    numeric = _to_numeric(series)
    numeric_ratio = float(numeric.notna().mean())
    integer_ratio = float((numeric.dropna().mod(1).eq(0)).mean()) if numeric.notna().any() else 0.0
    datetimes = _to_datetime(series)
    datetime_ratio = float(datetimes.notna().mean())
    lowered = as_string.str.lower()
    boolean_ratio = float(lowered.isin({"true", "false", "0", "1", "yes", "no"}).mean())
    leading_zero_ratio = float(as_string.str.match(r"^0\d+$").mean())
    evidence = {
        "numeric_parse_ratio": round(numeric_ratio, 6),
        "integer_parse_ratio": round(integer_ratio, 6),
        "datetime_parse_ratio": round(datetime_ratio, 6),
        "boolean_parse_ratio": round(boolean_ratio, 6),
        "leading_zero_ratio": round(leading_zero_ratio, 6),
        "string_ratio": 1.0,
    }
    if numeric_ratio >= 0.9 and leading_zero_ratio >= 0.1:
        return "integer_like_string", round(numeric_ratio, 6), evidence
    if numeric_ratio >= 0.9:
        if integer_ratio >= 0.98:
            return "integer", round(min(numeric_ratio, integer_ratio), 6), evidence
        return "float", round(numeric_ratio, 6), evidence
    if datetime_ratio >= 0.9:
        return "datetime", round(datetime_ratio, 6), evidence
    if boolean_ratio >= 0.9:
        return "boolean", round(boolean_ratio, 6), evidence
    if 0.1 < numeric_ratio < 0.9 or 0.1 < datetime_ratio < 0.9:
        evidence["mixed_type_ratio"] = round(max(numeric_ratio, datetime_ratio), 6)
        return "mixed", round(max(numeric_ratio, datetime_ratio), 6), evidence
    return "string", 0.75, evidence


def _miscast_mask(series: pd.Series, expected_type: Any) -> pd.Series:
    if len(series) == 0:
        return pd.Series(False, index=series.index)
    normalized = str(expected_type or "").lower()
    if normalized in {"int", "integer", "float", "double", "number", "numeric", "decimal", "numeric_string", "integer_like_string"}:
        return _to_numeric(series).isna()
    if normalized in {"date", "datetime", "timestamp"}:
        return _to_datetime(series).isna()
    if normalized in {"bool", "boolean"}:
        return ~series.astype(str).str.lower().isin({"true", "false", "0", "1", "yes", "no"})
    return pd.Series(False, index=series.index)


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def _to_datetime(series: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(series, errors="coerce")


def _top_values(series: pd.Series) -> dict[str, float]:
    total = len(series)
    return {str(k): _ratio(v, total) for k, v in series.value_counts(dropna=True).head(TOP_K_VALUES).items()}


def _top_values_detail(series: pd.Series, null_count: int, blank_count: int) -> list[dict[str, Any]]:
    total = len(series) + null_count
    rows: list[dict[str, Any]] = []
    if null_count:
        rows.append({"value": None, "count": null_count, "ratio": _ratio(null_count, total), "is_null": True, "is_blank": False})
    if blank_count:
        rows.append({"value": "", "count": blank_count, "ratio": _ratio(blank_count, total), "is_null": False, "is_blank": True})
    non_blank = series[~series.astype("string").str.strip().eq("").fillna(False)]
    for value, count in non_blank.value_counts(dropna=True).head(TOP_K_VALUES).items():
        display = str(value)
        if len(display) > TOP_VALUE_MAX_LENGTH:
            display = display[:TOP_VALUE_MAX_LENGTH] + "..."
        rows.append({"value": display, "count": int(count), "ratio": _ratio(count, total), "is_null": False, "is_blank": False})
    return rows[:TOP_K_VALUES]


def _pattern_frequency(series: pd.Series) -> dict[str, float]:
    total = len(series)
    counts: Counter[str] = Counter()
    for value in series.astype(str):
        if EMAIL_RE.match(value):
            counts["valid_email_format"] += 1
        else:
            counts[_shape(value)] += 1
    return {pattern: _ratio(count, total) for pattern, count in counts.most_common(PATTERN_TOP_K)}


def _patterns_detail(pattern_frequency: dict[str, float], series: pd.Series) -> list[dict[str, Any]]:
    examples: dict[str, str] = {}
    for value in series.astype(str):
        pattern = "valid_email_format" if EMAIL_RE.match(value) else _shape(value)
        examples.setdefault(pattern, _mask_example(value))
    return [
        {"pattern": pattern, "ratio": ratio, "example_masked": examples.get(pattern)}
        for pattern, ratio in pattern_frequency.items()
    ]


def _length_distribution(series: pd.Series) -> dict[str, float]:
    total = len(series)
    counts = series.astype(str).str.len().value_counts().sort_index()
    return {str(k): _ratio(v, total) for k, v in counts.items()}


def _length_summary(series: pd.Series) -> dict[str, Any]:
    if len(series) == 0:
        return {}
    lengths = series.astype(str).str.len()
    return {
        "min_length": int(lengths.min()),
        "max_length": int(lengths.max()),
        "mean_length": _finite(lengths.mean()),
        "median_length": _finite(lengths.median()),
        "p25_length": _finite(lengths.quantile(0.25)),
        "p75_length": _finite(lengths.quantile(0.75)),
        "p95_length": _finite(lengths.quantile(0.95)),
    }


def _numeric_summary(values: pd.Series) -> dict[str, Any]:
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = (values < lower) | (values > upper)
    return {
        "min": _finite(values.min()),
        "max": _finite(values.max()),
        "mean": _finite(values.mean()),
        "median": _finite(values.median()),
        "standard_deviation": _finite(values.std(ddof=0)),
        "p01": _finite(values.quantile(0.01)),
        "p05": _finite(values.quantile(0.05)),
        "p25": _finite(q1),
        "p75": _finite(q3),
        "p95": _finite(values.quantile(0.95)),
        "p99": _finite(values.quantile(0.99)),
        "negative_count": int((values < 0).sum()),
        "zero_count": int((values == 0).sum()),
        "positive_count": int((values > 0).sum()),
        "iqr_lower_bound": _finite(lower),
        "iqr_upper_bound": _finite(upper),
        "outlier_count": int(outliers.sum()),
        "outlier_ratio": _ratio(int(outliers.sum()), len(values)),
    }


def _miscast_examples(series: pd.Series, miscast_mask: pd.Series) -> list[str]:
    return [_mask_example(str(value)) for value in series[miscast_mask].astype(str).head(MISCAST_EXAMPLE_LIMIT)]


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


def _mask_example(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "***" + value[-2:]


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _ratio_or_none(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator), 6) if denominator else None


def _finite(value: Any) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _safe_string(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return str(value)
