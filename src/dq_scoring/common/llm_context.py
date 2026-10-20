"""Deny-by-default external LLM context.

Only typed, bounded aggregates and opaque tokens are representable. Column names, descriptions,
values, extrema, identifiers and file/object names have no field here, so they cannot egress.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TechnicalType = Literal["STRING", "INTEGER", "DOUBLE", "DATE", "TIMESTAMP", "JSON"]
TECHNICAL_TYPES = frozenset(TechnicalType.__args__)
MAX_TOKENS = 1000
_COUNT = Field(ge=0, le=10**12)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnContext(_Strict):
    token: str = Field(pattern=r"^c\d{3}$")
    type: TechnicalType
    sample_rows: int = _COUNT
    null_count: int = _COUNT
    non_null_count: int = _COUNT
    distinct_count: int = _COUNT
    parse_success_count: int = _COUNT


class RecommendationContext(_Strict):
    total_rows: int = _COUNT
    sample_rows: int = _COUNT
    columns: list[ColumnContext] = Field(min_length=1, max_length=200)


class DimensionContext(_Strict):
    dimension: Literal["COMPLETENESS", "ACCURACY", "CONSISTENCY", "TIMELINESS", "UNIQUENESS", "VALIDITY"]
    score: float | None = Field(default=None, ge=0, le=100)
    weight: float = Field(ge=0, le=1e6)
    coverage: float | None = Field(default=None, ge=0, le=1)


class RuleContext(_Strict):
    token: str = Field(pattern=r"^r\d{3}$")
    dimension: Literal["COMPLETENESS", "ACCURACY", "CONSISTENCY", "TIMELINESS", "UNIQUENESS", "VALIDITY"]
    rule_type: str = Field(pattern=r"^[A-Z_]{1,24}$")
    measurement_status: Literal[
        "MEASURED", "NOT_APPLICABLE", "NOT_MEASURABLE", "INSUFFICIENT_DATA", "SKIPPED_BY_BUDGET", "FAILED_TO_MEASURE"
    ]
    score: float | None = Field(default=None, ge=0, le=100)
    passed: int = _COUNT
    failed: int = _COUNT
    missing: int = _COUNT
    miscast: int = _COUNT
    not_applicable: int = _COUNT
    total_observed: int = _COUNT
    weight: float = Field(ge=0, le=1e6)
    is_required: bool
    is_critical: bool
    is_advisory: bool


class NarrativeContext(_Strict):
    dq_score: float | None = Field(default=None, ge=0, le=100)
    coverage: float | None = Field(default=None, ge=0, le=1)
    quality_gate: Literal["PASS", "WARN", "FAIL", "INSUFFICIENT_EVIDENCE", "ERROR"]
    publication_status: Literal["PUBLISHED", "WITHHELD"]
    dimensions: list[DimensionContext] = Field(max_length=6)
    rules: list[RuleContext] = Field(max_length=100)
    rules_truncated: bool


def _count(value: Any) -> int | None:
    """A real count, or None when absent/invalid/out of bounds (never coerced to zero)."""
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**12
    return value if ok else None


def _column_context(token: str, stat: dict, default_sample_rows: int | None) -> ColumnContext | None:
    """Validated aggregates, or None (column excluded) when counts are missing or inconsistent."""
    sample = _count(stat.get("sample_rows", default_sample_rows))
    nulls, non_null = _count(stat.get("null_count")), _count(stat.get("non_null_count"))
    distinct, parsed = _count(stat.get("distinct_count")), _count(stat.get("parse_success_count"))
    if None in (sample, nulls, non_null, distinct, parsed):
        return None
    if nulls + non_null != sample or distinct > non_null or parsed > non_null:
        return None
    hint = stat.get("type_hint")
    return ColumnContext(
        token=token, type=hint if hint in TECHNICAL_TYPES else "STRING", sample_rows=sample,
        null_count=nulls, non_null_count=non_null, distinct_count=distinct, parse_success_count=parsed,
    )


def canonical_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def context_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def build_recommendation_context(
    schema: dict, profile: dict, protected: frozenset[str], total_rows: int | None, max_columns: int
) -> tuple[RecommendationContext | None, dict[str, str]]:
    """Return (context, token -> local column name). Protected and unprofiled columns are omitted."""
    stats = {c.get("name"): c for c in (profile or {}).get("columns", []) if isinstance(c, dict)}
    columns: list[ColumnContext] = []
    tokens: dict[str, str] = {}
    for index, column in enumerate((schema or {}).get("columns", [])):
        name = column if isinstance(column, str) else column.get("name")
        stat = stats.get(name)
        if len(columns) >= max_columns or index >= MAX_TOKENS:
            break
        if not isinstance(name, str) or name in protected or stat is None:
            continue
        token = f"c{index:03d}"
        column_context = _column_context(token, stat, _count((profile or {}).get("sample_rows")))
        if column_context is None:
            continue
        columns.append(column_context)
        tokens[token] = name
    total, sample = _count(total_rows), _count((profile or {}).get("sample_rows"))
    if not columns or total is None or sample is None:
        return None, {}
    return RecommendationContext(total_rows=total, sample_rows=sample, columns=columns), tokens
