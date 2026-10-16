"""Pure domain entities, enums, and value objects for the DQ Scoring Engine.

Follows Clean Architecture: zero I/O, zero external framework dependencies (pure Pydantic & standard library).
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityGateStatus(str, Enum):
    """6-Tier Quality Gate evaluation outcome (BR-010)."""

    ERROR = "ERROR"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    WARN = "WARN"
    PASS = "PASS"


class PublicationStatus(str, Enum):
    """Atomic scorecard publication status (BR-012)."""

    PUBLISHED = "PUBLISHED"
    WITHHELD = "WITHHELD"


class MeasurementStatus(str, Enum):
    """Standardized technical measurement execution status."""

    MEASURED = "MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_MEASURABLE = "NOT_MEASURABLE"
    FAILED_TO_MEASURE = "FAILED_TO_MEASURE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SKIPPED_BY_BUDGET = "SKIPPED_BY_BUDGET"


class StandardDimension(str, Enum):
    """6 Standard Data Quality Dimensions (ISO/IEC 25012 / DAMA)."""

    ACCURACY = "ACCURACY"
    COMPLETENESS = "COMPLETENESS"
    CONSISTENCY = "CONSISTENCY"
    TIMELINESS = "TIMELINESS"
    VALIDITY = "VALIDITY"
    UNIQUENESS = "UNIQUENESS"


class RuleCounts(BaseModel):
    """Partitioning record counts for an evaluation rule (DDIA Invariant).

    passed + failed + missing + miscast + not_applicable == total_observed.
    """

    model_config = ConfigDict(frozen=True)

    passed: int = 0
    failed: int = 0
    missing: int = 0
    miscast: int = 0
    not_applicable: int = 0
    total_observed: int = 0


class QualityRuleResult(BaseModel):
    """Canonical representation of an individual rule evaluation result."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    dimension: str
    measurement_status: str
    is_critical: bool = False
    is_advisory: bool = False
    is_required: bool = False
    gate_enabled: bool = True
    score_enabled: bool = True
    conflict_group: str | None = None
    is_primary_scoring_rule: bool = True
    contribution_weight: float = 1.0
    acceptance_threshold: float | None = None
    confidence: float | None = None
    computed_score: float | None = None
    violations_count: int = 0
    counts: RuleCounts | None = None
    evidence_samples: list[dict[str, Any]] | None = None
    error_message: str | None = None
    source_kind: str = "RULE"
    target_column: str | None = None
    rule_config_hash: str | None = None


class ScoringPolicy(BaseModel):
    """Tenant/Dataset-specific scoring and quality gate policy.

    Business thresholds and weights must never be hardcoded into business logic.
    """

    # extra="forbid": a misspelled field must fail loudly, never fall back to defaults.
    model_config = ConfigDict(frozen=True, extra="forbid")

    publication_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    warn_min: float = Field(default=60.0, ge=0.0, le=100.0)
    pass_min: float = Field(default=80.0, ge=0.0, le=100.0)
    min_critical_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    critical_acceptance_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    """Policy-wide score floor for critical rules without their own threshold; None = zero tolerance."""
    dimension_weights: dict[str, float] = Field(default_factory=dict)
    policy_id: UUID | None = None

    @model_validator(mode="after")
    def _check_threshold_order(self) -> ScoringPolicy:
        if self.warn_min > self.pass_min:
            raise ValueError("warn_min (gate fail threshold) must not exceed pass_min (gate warn threshold)")
        return self

    @property
    def coverage_threshold(self) -> float:
        """Compatibility alias for publication_threshold."""
        return self.publication_threshold

    @property
    def gate_fail_threshold(self) -> float:
        """Lower bound for WARN; below this triggers FAIL."""
        return self.warn_min

    @property
    def gate_warn_threshold(self) -> float:
        """Lower bound for PASS; below this triggers WARN."""
        return self.pass_min


class GateEvaluationInput(BaseModel):
    """Input payload for 6-tier Quality Gate evaluation."""

    model_config = ConfigDict(frozen=True)

    rule_results: list[QualityRuleResult]
    dq_score: float | None
    coverage_ratio: float | None = None
    policy: ScoringPolicy
    required_dimensions: set[str] = Field(default_factory=set)


class PublicationCheckInput(BaseModel):
    """Input payload for publication status determination."""

    model_config = ConfigDict(frozen=True)

    run_status: str
    gate_status: QualityGateStatus
    dq_score: float | None
    coverage_ratio: float | None = None
    policy: ScoringPolicy
    all_required_dimensions_measured: bool = True
    has_failed_required_rules: bool = False
    has_unmeasured_required_rules: bool = False


class DimensionResult(BaseModel):
    """Aggregated score and coverage for a single data quality dimension."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    dimension_score: float | None = None
    coverage_ratio: float | None = None
    rule_results: list[QualityRuleResult] = Field(default_factory=list)
    dimension_weight: float = 1.0


class DatasetScoreResult(BaseModel):
    """Final aggregated score, coverage, and dimension outcomes for a dataset snapshot."""

    model_config = ConfigDict(frozen=True)

    dq_score: float | None = None
    coverage_ratio: float | None = None
    dimension_results: list[DimensionResult] = Field(default_factory=list)
