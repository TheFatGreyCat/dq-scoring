from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True)
class ProfilingConfig:
    execution_mode: str = "gx_pandas"
    sampling_method: str = "full_scan"
    sample_fraction: float | None = None
    min_sample_size: int | None = None
    random_seed: int | None = None
    enable_pattern_detection: bool = True
    enable_candidate_rule_generation: bool = True
    enable_basic_anomaly_detection: bool = True
    baseline_window: int = 7
    thresholds: dict[str, Any] = field(default_factory=dict)
    chunk_size: int = 50_000
    memory_budget_mb: int = 512
    time_budget_sec: int = 300
    max_deep_columns: int = 100
    enable_null_heavy_sampling: bool = True
    enable_duplicate_aware_sampling: bool = True


@dataclass(frozen=True)
class DatasetConfig:
    dataset_id: str
    dataset_name: str | None
    dataset_type: str
    source_type: str
    storage_path: str
    declared_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=list)
    composite_key: list[str] = field(default_factory=list)
    business_key: list[str] = field(default_factory=list)
    mandatory_fields: list[str] = field(default_factory=list)
    cde_fields: list[str] = field(default_factory=list)
    timestamp_column: str | None = None
    freshness_time_basis: str = "updated_at"
    sla_config: dict[str, Any] = field(default_factory=dict)
    profiling_config: ProfilingConfig = field(default_factory=ProfilingConfig)


@dataclass
class SamplingInfo:
    sampling_method: str
    is_sampled: bool
    sample_fraction: float | None
    sample_size: int
    total_rows: int
    scan_mode: str = "full"
    sample_method: str | None = None
    random_seed: int | None = None
    coverage_estimate: float | None = None
    profile_confidence: float | None = None
    chunk_size: int | None = None
    memory_budget_mb: int | None = None
    time_budget_sec: int | None = None
    budget_used: dict[str, Any] = field(default_factory=dict)
    skipped_metrics: list[str] = field(default_factory=list)
    termination_reason: str | None = None
    deep_profiled_columns: list[str] = field(default_factory=list)
    profile_strategy: str = "dataframe_full"


@dataclass
class SchemaProfile:
    missing_columns: list[str]
    extra_columns: list[str]
    type_mismatches: list[dict[str, str]]
    nullable_mismatches: list[dict[str, str]]

    def to_record(self) -> dict[str, Any]:
        return {
            "missing_columns": self.missing_columns,
            "extra_columns": self.extra_columns,
            "type_mismatches": self.type_mismatches,
            "nullable_mismatches": self.nullable_mismatches,
        }


@dataclass
class ColumnProfile:
    run_id: str
    dataset_id: str
    column_name: str
    declared_data_type: str | None
    inferred_data_type: str
    null_count: int
    null_ratio: float
    blank_count: int
    distinct_count: int
    uniqueness_ratio: float | None
    metric_scope: str = "full"
    non_null_count: int = 0
    distinct_count_including_null: int = 0
    trimmed_blank_count: int = 0
    miscast_ratio: float = 0.0
    inferred_type_confidence: float | None = None
    inferred_type_evidence: dict[str, Any] = field(default_factory=dict)
    top_values_detail: list[dict[str, Any]] = field(default_factory=list)
    patterns_detail: list[dict[str, Any]] = field(default_factory=list)
    length_summary: dict[str, Any] = field(default_factory=dict)
    numeric_summary: dict[str, Any] = field(default_factory=dict)
    miscast_examples: list[str] = field(default_factory=list)
    min_value: str | None = None
    max_value: str | None = None
    mean_value: float | None = None
    std_value: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p99: float | None = None
    top_values: dict[str, float] = field(default_factory=dict)
    pattern_frequency: dict[str, float] = field(default_factory=dict)
    length_distribution: dict[str, float] = field(default_factory=dict)
    miscast_count: int = 0

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class DatasetProfile:
    run_id: str
    dataset_id: str
    row_count: int
    column_count: int
    duplicate_row_count: int
    duplicate_row_ratio: float
    last_updated_timestamp: str | None
    profiling_timestamp: str
    freshness_time_basis: str
    freshness_lag: float | None
    expected_row_count: int | None
    volume_deviation_rate: float | None
    profile_duration_seconds: float

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class CandidateRule:
    candidate_rule_id: str
    run_id: str
    dataset_id: str
    column_name: str | None
    dimension: str
    rule_type: str
    expectation_type: str | None
    proposed_threshold: float
    confidence: float
    evidence: dict[str, Any]
    status: str = "pending_review"
    created_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class AnomalyFlag:
    anomaly_id: str
    run_id: str
    dataset_id: str
    column_name: str | None
    anomaly_type: str
    severity: str
    description: str
    current_value: str
    baseline_value: str
    detected_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ProfilingRun:
    run_id: str
    dataset_id: str
    dataset_version: str | None
    run_timestamp: str
    execution_engine: str
    source_path: str
    schema_version: str | None
    sampling_method: str
    is_sampled: bool
    sample_fraction: float | None
    sample_size: int
    total_rows: int
    status: str
    error_message: str | None = None
    scan_mode: str = "full"
    sample_method: str | None = None
    sample_ratio: float | None = None
    random_seed: int | None = None
    coverage_estimate: float | None = None
    profile_confidence: float | None = None
    chunk_size: int | None = None
    memory_budget_mb: int | None = None
    time_budget_sec: int | None = None
    budget_used: dict[str, Any] = field(default_factory=dict)
    skipped_metrics: list[str] = field(default_factory=list)
    termination_reason: str | None = None
    deep_profiled_columns: list[str] = field(default_factory=list)
    profile_strategy: str = "dataframe_full"

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ProfileResult:
    profiling_run: ProfilingRun
    schema_profile: SchemaProfile
    dataset_profile: DatasetProfile
    column_profiles: list[ColumnProfile]
    candidate_rules: list[CandidateRule]
    anomaly_flags: list[AnomalyFlag]

    def to_artifact(self) -> dict[str, Any]:
        return {
            "profiling_run": self.profiling_run.to_record(),
            "schema_profile": self.schema_profile.to_record(),
            "dataset_profile": self.dataset_profile.to_record(),
            "column_profile": [profile.to_record() for profile in self.column_profiles],
            "candidate_rules": [rule.to_record() for rule in self.candidate_rules],
            "anomaly_flags": [flag.to_record() for flag in self.anomaly_flags],
        }

    def to_summary(self, store_path: str) -> dict[str, Any]:
        return {
            "run_id": self.profiling_run.run_id,
            "status": self.profiling_run.status,
            "dataset_id": self.profiling_run.dataset_id,
            "row_count": self.dataset_profile.row_count,
            "column_count": self.dataset_profile.column_count,
            "candidate_rule_count": len(self.candidate_rules),
            "anomaly_flag_count": len(self.anomaly_flags),
            "profile_store": store_path,
        }

