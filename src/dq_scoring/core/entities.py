"""Pure domain entities and lifecycle representations."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dq_scoring.core.models import (
    DimensionResult,
    MeasurementStatus,
    PublicationStatus,
    QualityGateStatus,
    RuleCounts,
    ScoringPolicy,
)


class RunStatus(StrEnum):
    """Lifecycle status for an evaluation run."""

    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DataAsset(BaseModel):
    """Logical data asset owned by a tenant."""

    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    tenant_id: UUID
    name: str
    created_at: datetime


class DatasetSnapshot(BaseModel):
    """Immutable point-in-time snapshot of a Data Asset."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID
    tenant_id: UUID
    asset_id: UUID
    source_kind: str
    source_descriptor: dict[str, Any]
    schema_definition: dict[str, Any]
    total_rows: int
    total_columns: int
    captured_at: datetime


class QualityRule(BaseModel):
    """Configured data quality rule to be executed against a snapshot."""

    model_config = ConfigDict(frozen=True)

    rule_id: UUID
    rule_code: str
    dimension: str
    rule_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    null_policy: str = "fail"
    is_required: bool = False
    is_critical: bool = False
    gate_enabled: bool = True
    score_enabled: bool = True
    conflict_group: str | None = None
    is_primary_scoring_rule: bool = True
    contribution_weight: float = 1.0
    acceptance_threshold: float | None = None
    is_advisory: bool = False
    ruleset_id: UUID | None = None


class RunSpec(BaseModel):
    """Execution specification for an evaluation run."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    tenant_id: UUID
    snapshot: DatasetSnapshot
    rules: list[QualityRule]
    policy: ScoringPolicy
    execution_profile: str = "standard"
    outlier_columns: list[str] = Field(default_factory=list)
    ruleset_id: UUID | None = None
    policy_id: UUID | None = None
    created_by: UUID | None = None


class LeasedRun(BaseModel):
    """Claimed run instance protected by monotonic lease generation."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    worker_id: str
    lease_generation: int
    claimed_at: datetime
    lease_expires_at: datetime
    spec: RunSpec


class ImmutableAssessment(BaseModel):
    """Persisted, immutable scorecard assessment result."""

    model_config = ConfigDict(frozen=True)

    assessment_id: UUID
    tenant_id: UUID
    run_id: UUID
    snapshot_id: UUID
    dq_score: float | None
    publication_status: PublicationStatus
    coverage_ratio: float | None
    quality_gate: QualityGateStatus
    dimension_results: list[DimensionResult]
    assessment_hash: str
    created_at: datetime
    confidence_status: str = "NOT_APPLICABLE"


class CanonicalMetric(BaseModel):
    """Single-pass canonical statistical metric."""

    model_config = ConfigDict(frozen=True)

    metric_name: str
    column_name: str
    metric_value: float | int | str | None = None


class RuleExecutionOutput(BaseModel):
    """Execution output from compute engine for a single rule."""

    model_config = ConfigDict(frozen=True)

    rule_id: UUID
    counts: RuleCounts
    status: MeasurementStatus = MeasurementStatus.MEASURED
    evidence_samples: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None


class OutlierExecutionOutput(BaseModel):
    """Execution output from compute engine for IQR outlier detection."""

    model_config = ConfigDict(frozen=True)

    column_name: str
    total_evaluated: int
    iqr: float
    outlier_count: int
    outlier_samples: list[dict[str, Any]] = Field(default_factory=list)
