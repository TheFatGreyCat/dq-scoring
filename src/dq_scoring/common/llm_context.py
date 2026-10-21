"""Deny-by-default external LLM context.

Only typed, bounded aggregates and opaque tokens are representable. Column names, descriptions,
values, extrema, identifiers and file/object names have no field here, so they cannot egress.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SEMANTIC_VOCABULARY_VERSION = "dq-semantic-v1"
SemanticLabel = Literal[
    "UNKNOWN", "IDENTIFIER", "CATEGORY", "FREE_TEXT", "QUANTITY", "MONEY", "DATE_TIME", "EMAIL", "PHONE", "ADDRESS",
    "PERSON_NAME", "BOOLEAN",
]
SEMANTIC_LABELS: frozenset[str] = frozenset(SemanticLabel.__args__)

TechnicalType = Literal["STRING", "INTEGER", "DOUBLE", "DATE", "TIMESTAMP", "JSON", "BOOLEAN", "OTHER"]
PARSE_TARGETS = ("INTEGER", "DOUBLE", "DATE", "TIMESTAMP")
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
    distinct_count: int | None = Field(default=None, ge=0, le=10**12)
    parse_success_count: int | None = Field(default=None, ge=0, le=10**12)
    semantic: SemanticLabel | None = None


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


def real_count(value: Any) -> int | None:
    """A real count, or None when absent/invalid/out of bounds (never coerced to zero)."""
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**12
    return value if ok else None


def profile_rows(profile: dict) -> Any:
    """Rows actually scanned: FULL `scanned_rows`, else the SAMPLE prefix `sample_rows`."""
    return profile.get("scanned_rows", profile.get("sample_rows"))


def profile_scope(profile: dict) -> dict:
    """Actual provenance of the selected profile; absent mode means the legacy SAMPLE import profile."""
    return {
        "mode": profile.get("mode", "SAMPLE"), "is_sample": profile.get("is_sample", True), "rows": profile_rows(profile),
        "profile_id": str(profile["profile_id"]) if profile.get("profile_id") else None,
        "fingerprint": profile.get("fingerprint"), "profiler_version": profile.get("profiler_version"),
    }


def parse_spec(stat: dict) -> tuple[str, str | None] | None:
    """(parse target, format) only when the profile states an explicit target; never guessed."""
    explicit = "parse_target" in stat or "technical_type" in stat
    target = stat.get("parse_target") if explicit else stat.get("type_hint")
    fmt = stat.get("parse_format") if explicit else stat.get("timestamp_format")
    if target not in PARSE_TARGETS:
        return None
    if target == "DATE" and not fmt:
        fmt = "yyyy-MM-dd"
    if target == "TIMESTAMP" and not fmt:
        return None
    return target, fmt if target in ("DATE", "TIMESTAMP") else None


def technical_type(stat: dict) -> str:
    if "technical_type" in stat:
        kind = str(stat["technical_type"]).upper()
        return kind if kind in TECHNICAL_TYPES else "OTHER"
    return stat.get("type_hint") if stat.get("type_hint") in TECHNICAL_TYPES else "STRING"


def column_aggregates(token: str, stat: dict, default_rows: int | None, full: bool, semantic: str | None = None) -> ColumnContext | None:
    """Validated aggregates, or None (column excluded) when counts are missing or inconsistent.

    FULL profiles may carry null distinct/parse metrics (unknown); they stay null, never zero.
    """
    rows = real_count(stat.get("sample_rows", default_rows))
    nulls, non_null = real_count(stat.get("null_count")), real_count(stat.get("non_null_count"))
    distinct, parsed = real_count(stat.get("distinct_count")), real_count(stat.get("parse_success_count"))
    if None in (rows, nulls, non_null) or (not full and None in (distinct, parsed)):
        return None
    if nulls + non_null != rows or (distinct or 0) > non_null or (parsed or 0) > non_null:
        return None
    return ColumnContext(
        token=token, type=technical_type(stat), sample_rows=rows, null_count=nulls, non_null_count=non_null,
        distinct_count=distinct, parse_success_count=parsed, semantic=semantic if semantic in SEMANTIC_LABELS else None,
    )


def canonical_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def context_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def build_recommendation_context(
    schema: dict, profile: dict, protected: frozenset[str], total_rows: int | None, max_columns: int,
    confirmed: dict[str, str] | None = None,
) -> tuple[RecommendationContext | None, dict[str, str]]:
    """Return (context, token -> local column name). Only confirmed, unprotected, profiled columns are emitted."""
    stats = {c.get("name"): c for c in (profile or {}).get("columns", []) if isinstance(c, dict)}
    confirmed = {k: v for k, v in (confirmed or {}).items() if v in SEMANTIC_LABELS}
    columns: list[ColumnContext] = []
    tokens: dict[str, str] = {}
    for index, column in enumerate((schema or {}).get("columns", [])):
        name = column if isinstance(column, str) else column.get("name")
        stat = stats.get(name)
        if len(columns) >= max_columns or index >= MAX_TOKENS:
            break
        if not isinstance(name, str) or name in protected or stat is None or name not in confirmed:
            continue
        token = f"c{index:03d}"
        column_context = column_aggregates(
            token, stat, real_count(profile_rows(profile or {})), (profile or {}).get("mode") == "FULL", confirmed[name],
        )
        if column_context is None:
            continue
        columns.append(column_context)
        tokens[token] = name
    total, sample = real_count(total_rows), real_count(profile_rows(profile or {}))
    if not columns or total is None or sample is None:
        return None, {}
    return RecommendationContext(total_rows=total, sample_rows=sample, columns=columns), tokens
