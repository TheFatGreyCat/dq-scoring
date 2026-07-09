from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from profiling.models import ColumnProfile


EMAIL_NAME_RE = re.compile(r"(^|_)e?mail($|_)", re.I)
PHONE_NAME_RE = re.compile(r"phone|mobile|tel", re.I)
ID_NAME_RE = re.compile(r"(^id$|_id$|identifier|code|number$|no$)", re.I)
AMOUNT_NAME_RE = re.compile(r"amount|price|cost|revenue|total|balance|qty|quantity", re.I)
AGE_NAME_RE = re.compile(r"(^|_)age($|_)", re.I)
DATE_NAME_RE = re.compile(r"date|time|timestamp|updated_at|created_at", re.I)
CATEGORY_NAME_RE = re.compile(r"status|type|category|segment|class", re.I)


@dataclass(frozen=True)
class SemanticDetectionResult:
    column_name: str
    semantic_type: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


def detect_semantics(column_profiles: list[ColumnProfile]) -> list[SemanticDetectionResult]:
    return [detect_column_semantic(profile) for profile in column_profiles]


def detect_column_semantic(profile: ColumnProfile) -> SemanticDetectionResult:
    name = profile.column_name.lower()
    candidates: list[tuple[str, float, dict[str, Any]]] = []

    email_ratio = profile.pattern_frequency.get("valid_email_format", 0.0)
    if EMAIL_NAME_RE.search(name) or email_ratio >= 0.7:
        candidates.append(("email", max(0.70 if EMAIL_NAME_RE.search(name) else 0.0, min(0.99, email_ratio + 0.15)), {"email_pattern_ratio": email_ratio}))

    dominant_shape, shape_ratio = _dominant(profile.pattern_frequency)
    if PHONE_NAME_RE.search(name) or _phone_shape(dominant_shape, shape_ratio):
        confidence = 0.78 if PHONE_NAME_RE.search(name) else 0.65
        if _phone_shape(dominant_shape, shape_ratio):
            confidence = max(confidence, min(0.95, shape_ratio + 0.10))
        candidates.append(("phone", confidence, {"dominant_pattern": dominant_shape, "dominant_pattern_ratio": shape_ratio}))

    if ID_NAME_RE.search(name) or profile.uniqueness_ratio >= 0.95:
        confidence = 0.82 if ID_NAME_RE.search(name) else min(0.90, profile.uniqueness_ratio)
        candidates.append(("identifier", confidence, {"uniqueness_ratio": profile.uniqueness_ratio}))

    if AGE_NAME_RE.search(name):
        candidates.append(("age", 0.90 if profile.inferred_data_type == "numeric" else 0.72, {"inferred_type": profile.inferred_data_type}))

    if AMOUNT_NAME_RE.search(name) and profile.inferred_data_type == "numeric":
        candidates.append(("amount", 0.86, {"min_value": profile.min_value, "max_value": profile.max_value}))

    if DATE_NAME_RE.search(name) or profile.inferred_data_type == "datetime":
        confidence = 0.86 if DATE_NAME_RE.search(name) else 0.78
        candidates.append(("datetime", confidence, {"inferred_type": profile.inferred_data_type}))

    if CATEGORY_NAME_RE.search(name) or (profile.distinct_count > 0 and profile.distinct_count <= 20 and profile.uniqueness_ratio <= 0.5):
        confidence = 0.78 if CATEGORY_NAME_RE.search(name) else 0.66
        candidates.append(("category", confidence, {"distinct_count": profile.distinct_count, "uniqueness_ratio": profile.uniqueness_ratio}))

    if not candidates:
        return SemanticDetectionResult(profile.column_name, "unknown", 0.0, {"inferred_type": profile.inferred_data_type})

    semantic_type, confidence, evidence = max(candidates, key=lambda item: item[1])
    evidence = {**evidence, "inferred_type": profile.inferred_data_type, "column_name": profile.column_name}
    return SemanticDetectionResult(profile.column_name, semantic_type, round(float(confidence), 6), evidence)


def _dominant(values: dict[str, float]) -> tuple[str | None, float]:
    if not values:
        return None, 0.0
    key = max(values, key=values.get)
    return key, float(values[key])


def _phone_shape(pattern: str | None, ratio: float) -> bool:
    if not pattern or ratio < 0.6:
        return False
    digits = pattern.count("9")
    return 9 <= digits <= 12 and pattern.replace("9", "").strip(" +-().") == ""
