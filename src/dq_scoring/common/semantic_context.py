"""Column semantic evidence and provider payloads.

Evidence is advisory: bounded, deterministic, reason codes only. Semantic labels never change privacy
protection. The API payload can only represent opaque tokens, technical aggregates and *confirmed*
labels; the LOCAL payload additionally carries the column name, never values or extrema.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pydantic import Field

from dq_scoring.common.llm_context import (
    MAX_TOKENS,
    SEMANTIC_LABELS,
    SEMANTIC_VOCABULARY_VERSION,
    ColumnContext,
    SemanticLabel,
    _Strict,
    canonical_json,
    column_aggregates,
    context_sha256,
    profile_rows,
    real_count,
    technical_type,
)

__all__ = [
    "SEMANTIC_LABELS",
    "SEMANTIC_VOCABULARY_VERSION",
    "ApiSemanticContext",
    "LocalSemanticContext",
    "SemanticLabel",
    "build_api_context",
    "build_local_context",
    "canonical_json",
    "context_sha256",
    "local_evidence",
]

MAX_NAME_LENGTH = 256
_PERSONAL = frozenset({"BASIC_PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA"})
_TEMPORAL = frozenset({"DATE", "TIMESTAMP"})
_NUMERIC = frozenset({"INTEGER", "DOUBLE"})
_LOW_CARDINALITY = 20
# Ordered: first matching label wins. Words are whole name tokens, never substrings.
_NAME_HINTS: tuple[tuple[str, frozenset[str]], ...] = (
    ("EMAIL", frozenset({"email", "mail"})),
    ("PHONE", frozenset({"phone", "tel", "mobile", "msisdn"})),
    ("ADDRESS", frozenset({"address", "addr", "street"})),
    ("PERSON_NAME", frozenset({"firstname", "lastname", "fullname", "surname", "forename"})),
    ("IDENTIFIER", frozenset({"id", "uuid", "guid", "key"})),
    ("MONEY", frozenset({"amount", "price", "cost", "fare", "revenue", "salary", "fee"})),
    ("QUANTITY", frozenset({"qty", "quantity", "count", "units", "weight"})),
    ("DATE_TIME", frozenset({"date", "time", "timestamp", "datetime"})),
    ("BOOLEAN", frozenset({"flag", "active", "enabled"})),
    ("FREE_TEXT", frozenset({"comment", "comments", "description", "note", "notes", "remark", "text"})),
    ("CATEGORY", frozenset({"type", "category", "status", "kind", "class", "group"})),
)
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


class LocalColumn(ColumnContext):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)


class LocalSemanticContext(_Strict):
    columns: list[LocalColumn] = Field(min_length=1, max_length=200)


class ApiSemanticContext(_Strict):
    columns: list[ColumnContext] = Field(min_length=1, max_length=200)


def _words(name: str) -> frozenset[str]:
    return frozenset(w.lower() for w in _WORD.findall(name))


def _name_label(name: str) -> str | None:
    words = _words(name)
    if "name" in words and words & {"first", "last", "full", "given", "family", "middle"}:
        return "PERSON_NAME"
    return next((label for label, hints in _NAME_HINTS if words & hints), None)


def _column_names(schema: dict) -> Iterator[tuple[int, str]]:
    for index, column in enumerate((schema or {}).get("columns", [])):
        name = column if isinstance(column, str) else column.get("name") if isinstance(column, dict) else None
        if isinstance(name, str) and name:
            yield index, name


def _evidence(name: str, stat: dict | None, categories: set[str]) -> dict:
    kind = technical_type(stat) if stat else None
    label: str = "UNKNOWN"
    reasons: list[str] = []
    confidence = 0.0
    if kind == "BOOLEAN":
        label, reasons, confidence = "BOOLEAN", ["TYPE_BOOLEAN"], 0.8
    elif kind in _TEMPORAL:
        label, reasons, confidence = "DATE_TIME", ["TYPE_TEMPORAL"], 0.8
    hinted = _name_label(name)
    if hinted and label == "UNKNOWN":
        label, reasons, confidence = hinted, [f"NAME_HINT_{hinted}"], 0.5
    elif hinted == label and hinted:
        reasons.append(f"NAME_HINT_{hinted}")
        confidence = min(confidence + 0.1, 0.9)
    if label == "UNKNOWN":
        return {"column": name, "suggested_label": "UNKNOWN", "reason_codes": ["NO_SEMANTIC_EVIDENCE"],
                "confidence": 0.0, "source": "LOCAL_EVIDENCE"}
    non_null, distinct = real_count((stat or {}).get("non_null_count")), real_count((stat or {}).get("distinct_count"))
    parsed = real_count((stat or {}).get("parse_success_count"))
    if label in ("MONEY", "QUANTITY") and kind in _NUMERIC:
        reasons.append("TYPE_NUMERIC")
        confidence += 0.2
    elif label in ("MONEY", "QUANTITY") and kind is not None:
        reasons.append("TYPE_NOT_NUMERIC")
    if label == "IDENTIFIER" and non_null and distinct == non_null:
        reasons.append("DISTINCT_EQUALS_NON_NULL")
        confidence += 0.2
    if label == "CATEGORY" and distinct is not None and non_null and distinct <= _LOW_CARDINALITY and distinct < non_null:
        reasons.append("LOW_CARDINALITY")
        confidence += 0.2
    if label == "DATE_TIME" and parsed and non_null and parsed == non_null:
        reasons.append("ALL_NON_NULL_PARSE")
        confidence += 0.1
    if label in ("EMAIL", "PHONE", "ADDRESS", "PERSON_NAME") and categories & _PERSONAL:
        reasons.append("PRIVACY_PERSONAL_DATA")
        confidence += 0.2
    return {"column": name, "suggested_label": label, "reason_codes": reasons,
            "confidence": round(min(confidence, 0.95), 2), "source": "LOCAL_EVIDENCE"}


def local_evidence(schema: dict, profile: dict, privacy_columns: list[dict]) -> list[dict]:
    stats = {c.get("name"): c for c in (profile or {}).get("columns", []) if isinstance(c, dict)}
    categories = {
        c.get("column_name"): set(c.get("effective_categories") or []) for c in privacy_columns or [] if isinstance(c, dict)
    }
    return [_evidence(name, stats.get(name), categories.get(name, set())) for _, name in _column_names(schema)]


def _eligible(
    schema: dict, profile: dict, protected: frozenset[str], confirmed: dict[str, str], max_columns: int, confirmed_only: bool
) -> Iterator[tuple[str, str, ColumnContext]]:
    stats = {c.get("name"): c for c in (profile or {}).get("columns", []) if isinstance(c, dict)}
    rows = real_count(profile_rows(profile or {}))
    full = (profile or {}).get("mode") == "FULL"
    emitted = 0
    for index, name in _column_names(schema):
        if emitted >= max_columns or index >= MAX_TOKENS:
            return
        label = confirmed.get(name)
        label = label if label in SEMANTIC_LABELS else None
        if name in protected or name not in stats or len(name) > MAX_NAME_LENGTH or (confirmed_only and label is None):
            continue
        token = f"c{index:03d}"
        column = column_aggregates(token, stats[name], rows, full, label)
        if column is not None:
            emitted += 1
            yield token, name, column


def build_local_context(
    schema: dict, profile: dict, protected: frozenset[str], confirmed: dict[str, str], max_columns: int
) -> tuple[LocalSemanticContext | None, dict[str, str]]:
    items = list(_eligible(schema, profile, protected, confirmed, max_columns, confirmed_only=False))
    if not items:
        return None, {}
    columns = [LocalColumn(name=name, **column.model_dump()) for _, name, column in items]
    return LocalSemanticContext(columns=columns), {token: name for token, name, _ in items}


def build_api_context(
    schema: dict, profile: dict, protected: frozenset[str], confirmed: dict[str, str], max_columns: int
) -> tuple[ApiSemanticContext | None, dict[str, str]]:
    items = list(_eligible(schema, profile, protected, confirmed, max_columns, confirmed_only=True))
    if not items:
        return None, {}
    return ApiSemanticContext(columns=[column for _, _, column in items]), {token: name for token, name, _ in items}
