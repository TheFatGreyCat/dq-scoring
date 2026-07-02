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
class RuleConfig:
    rule_id: str
    dataset_id: str
    rule_type: str
    status: str
    score_enabled: bool
    rule_name: str | None = None
    description: str | None = None
    target_table: str | None = None
    target_column: str | None = None
    dimension: str | None = None
    scope_filter: dict[str, Any] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    null_policy: str = "ignore"
    threshold: float | None = None
    severity: str = "medium"
    execution_backend: str = "pandas"
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    mask_actual_value: bool = False

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RuleRun:
    rule_run_id: str
    dataset_id: str
    dataset_version: str | None
    run_timestamp: str
    execution_engine: str
    source_path: str
    rule_config_path: str
    status: str
    total_rules: int
    measured_rules: int
    not_measured_rules: int
    skipped_rules: int
    error_message: str | None = None

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RuleEvaluationResult:
    rule_run_id: str
    rule_id: str
    dataset_id: str
    target_table: str | None
    target_column: str | None
    dimension: str | None
    evaluation_unit: str
    passed: int
    failed: int
    miscast: int
    empty: int
    not_applicable: int
    total_records_in_scope: int
    threshold: float | None
    measurement_status: str
    error_message: str | None
    evaluated_at: str

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RuleIssueSample:
    rule_run_id: str
    rule_id: str
    dataset_id: str
    record_key: str
    target_column: str | None
    actual_value: str | None
    expected_condition: str
    issue_type: str
    sampled_at: str

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RulesEngineResult:
    rule_run: RuleRun
    rule_configs: list[RuleConfig]
    rule_evaluation_results: list[RuleEvaluationResult]
    rule_issue_samples: list[RuleIssueSample]

    def to_artifact(self) -> dict[str, Any]:
        return {
            "rule_run": self.rule_run.to_record(),
            "rule_config": [rule.to_record() for rule in self.rule_configs],
            "rule_evaluation_result": [result.to_record() for result in self.rule_evaluation_results],
            "rule_issue_sample": [sample.to_record() for sample in self.rule_issue_samples],
        }

    def to_summary(self, store_path: str) -> dict[str, Any]:
        return {
            "rule_run_id": self.rule_run.rule_run_id,
            "status": self.rule_run.status,
            "dataset_id": self.rule_run.dataset_id,
            "measured_rules": self.rule_run.measured_rules,
            "not_measured_rules": self.rule_run.not_measured_rules,
            "skipped_rules": self.rule_run.skipped_rules,
            "issue_sample_count": len(self.rule_issue_samples),
            "rules_store": store_path,
        }
