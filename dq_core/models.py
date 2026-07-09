from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


DQ_DIMENSIONS = {
    "Completeness",
    "Accuracy",
    "Accuracy Proxy",
    "Consistency",
    "Timeliness",
    "Uniqueness",
    "Validity",
}
RULE_CATEGORIES = {"general", "business", "technical"}
MANAGEMENT_SCOPES = {"framework", "dataset"}
TARGET_SCOPES = {"column", "multiple_columns", "dataset"}
EVALUATION_SCOPES = {"record", "column_aggregate", "dataset_aggregate", "cross_field"}
NULL_POLICIES = {"fail", "ignore", "separate"}
SCORING_METHODS = {"pass_ratio", "freshness_decay", "gate_only"}
APPLICABILITY_STATUSES = {"applicable", "not_applicable"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    dataset_name: str | None
    dataset_type: str
    source_type: str
    storage_path: str
    created_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class DatasetVersion:
    dataset_version_id: str
    dataset_id: str
    version_label: str
    source_fingerprint: str | None
    row_count: int | None = None
    created_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class DatasetColumn:
    dataset_version_id: str
    column_name: str
    ordinal_position: int
    declared_data_type: str | None
    inferred_data_type: str | None = None
    nullable: bool | None = None
    semantic_type: str | None = None
    semantic_confidence: float | None = None
    is_business_key: bool = False
    is_cde: bool = False
    is_mandatory: bool = False
    is_identifier: bool = False
    is_timestamp: bool = False

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class RuleTemplate:
    rule_template_id: str
    rule_code: str
    rule_template_version: int
    rule_category: str
    dimension: str
    management_scope: str
    target_scope: str
    evaluation_scope: str
    operator: str
    applicability: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    normalization: dict[str, Any] = field(default_factory=dict)
    null_policy: str = "separate"
    accuracy_mode: str | None = None
    default_acceptance: float | None = None
    default_scoring_threshold: float | None = None
    default_severity: str = "medium"
    base_rule_weight: float = 1.0
    score_enabled: bool = True
    gate_enabled: bool = False
    scoring_method: str = "pass_ratio"
    locked: bool = True
    active: bool = True

    def __post_init__(self) -> None:
        _require("rule_category", self.rule_category, RULE_CATEGORIES)
        _require("dimension", self.dimension, DQ_DIMENSIONS)
        _require("management_scope", self.management_scope, MANAGEMENT_SCOPES)
        _require("target_scope", self.target_scope, TARGET_SCOPES)
        _require("evaluation_scope", self.evaluation_scope, EVALUATION_SCOPES)
        _require("null_policy", self.null_policy, NULL_POLICIES)
        _require("scoring_method", self.scoring_method, SCORING_METHODS)

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class DatasetRuleBinding:
    binding_id: str
    dataset_version_id: str
    rule_template_id: str
    target_columns: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    acceptance_threshold: float | None = None
    scoring_pass_threshold: float | None = None
    severity: str = "medium"
    backend: str = "python"
    status: str = "active"
    source: str = "framework_auto"
    recommendation_confidence: float | None = None
    applicability_status: str = "applicable"
    exception_reason: str | None = None
    score_enabled: bool = True
    gate_enabled: bool = False
    scoring_method: str = "pass_ratio"

    def __post_init__(self) -> None:
        _require("applicability_status", self.applicability_status, APPLICABILITY_STATUSES)
        _require("scoring_method", self.scoring_method, SCORING_METHODS)

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class RuleRecommendation:
    rule_template_id: str
    target_columns: list[str]
    reason: str
    confidence: float
    editable: bool
    source: str = "framework_auto"

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ScoringPolicy:
    scoring_policy_id: str
    dataset_type: str
    dimension_weights: dict[str, float]
    quality_gate_pass_threshold: float = 80.0
    quality_gate_warning_threshold: float = 65.0
    severity_weights: dict[str, float] = field(default_factory=lambda: {"critical": 1.50, "high": 1.25, "medium": 1.00, "low": 0.75})
    criticality_weights: dict[str, float] = field(default_factory=lambda: {"Critical": 1.50, "High": 1.25, "Medium": 1.10, "Normal": 1.00})

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class MeasurementResult:
    measurement_result_id: str
    validation_run_id: str
    binding_id: str
    evaluation_unit: str
    expectation_success: bool | None
    measurement_status: str
    observed_value: dict[str, Any] = field(default_factory=dict)
    expected_spec: dict[str, Any] = field(default_factory=dict)
    failure_breakdown: dict[str, Any] = field(default_factory=dict)
    backend: str = "python"
    execution_time_ms: int | None = None
    evaluated_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class RecordMeasurementSummary:
    measurement_result_id: str
    passed_count: int
    failed_count: int
    missing_count: int
    not_applicable_count: int
    records_in_scope: int

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class CanonicalValidationResult:
    validation_run_id: str
    dataset_version_id: str
    measurement_results: list[MeasurementResult]
    record_summaries: list[RecordMeasurementSummary]

    def summary_by_measurement_id(self) -> dict[str, RecordMeasurementSummary]:
        return {summary.measurement_result_id: summary for summary in self.record_summaries}


@dataclass(frozen=True)
class PipelineLog:
    log_id: str
    dataset_version_id: str | None
    event_type: str
    status: str
    message: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _require(field_name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ValueError(f"Unsupported {field_name} '{value}'")
