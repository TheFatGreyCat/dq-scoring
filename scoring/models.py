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
class ScoringConfig:
    dataset_type: str
    dimension_weights: dict[str, float]
    rule_weights: dict[str, float] = field(default_factory=dict)
    warning_margin: float = 3.0
    quality_gate_pass_threshold: float = 80.0
    quality_gate_warning_threshold: float = 65.0


@dataclass
class ScoreRun:
    run_id: str
    rule_run_id: str
    dataset_id: str
    run_timestamp: str
    scoring_config_path: str | None
    status: str
    rules_total: int
    rules_scored: int
    dimensions_measured: int
    error_message: str | None = None

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RuleScoreHistory:
    run_id: str
    dataset_id: str
    rule_id: str
    dimension: str | None
    target_column: str | None
    passed: int
    failed: int
    miscast: int
    empty: int
    not_applicable: int
    total_records_in_scope: int
    rule_score: float | None
    threshold: float | None
    measurement_status: str
    quality_status: str

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class DimensionScoreHistory:
    run_id: str
    dataset_id: str
    dimension: str
    dimension_score: float | None
    original_dimension_weight: float
    dimension_weight: float
    is_measured: bool
    measurement_status: str
    rules_total: int
    rules_failed: int
    rules_warning: int
    rules_passed: int

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class DatasetScoreHistory:
    run_id: str
    dataset_id: str
    dataset_version: str | None
    run_timestamp: str
    dq_core_score: float | None
    quality_gate_status: str
    total_records: int
    rules_total: int
    rules_failed: int
    measured_dimensions: list[str]
    excluded_dimensions: list[str]
    score_level: str = "dataset"

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ScoringResult:
    score_run: ScoreRun
    rule_score_history: list[RuleScoreHistory]
    dimension_score_history: list[DimensionScoreHistory]
    dataset_score_history: DatasetScoreHistory

    def to_artifact(self) -> dict[str, Any]:
        return {
            "score_run": self.score_run.to_record(),
            "rule_score_history": [score.to_record() for score in self.rule_score_history],
            "dimension_score_history": [score.to_record() for score in self.dimension_score_history],
            "dataset_score_history": self.dataset_score_history.to_record(),
        }

    def to_summary(self, store_path: str) -> dict[str, Any]:
        return {
            "run_id": self.score_run.run_id,
            "rule_run_id": self.score_run.rule_run_id,
            "status": self.score_run.status,
            "dataset_id": self.score_run.dataset_id,
            "dq_core_score": self.dataset_score_history.dq_core_score,
            "quality_gate_status": self.dataset_score_history.quality_gate_status,
            "rules_scored": self.score_run.rules_scored,
            "dimensions_measured": self.score_run.dimensions_measured,
            "score_store": store_path,
        }

