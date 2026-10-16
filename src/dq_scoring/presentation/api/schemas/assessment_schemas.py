"""Assessment scorecard request and response schemas conforming to AC-022."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CanonicalRuleResultResponse(BaseModel):
    """Detailed canonical quality rule evaluation result."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID | None = None
    """None for advisory signals (e.g. IQR outliers) that are not configured rules."""
    rule_code: str
    dimension: str
    target_column: str
    rule_type: str
    measurement_status: str
    computed_score: float | None = None
    passed_count: int
    failed_count: int
    missing_count: int
    miscast_count: int
    not_applicable_count: int
    total_observed: int
    violations_count: int
    weight: float
    is_required: bool
    is_critical: bool
    is_advisory: bool
    evidence_samples: list[dict[str, Any]] | None = None
    error_message: str | None = None


class DimensionResultResponse(BaseModel):
    """Dimension-level score and coverage result."""

    model_config = ConfigDict(from_attributes=True)

    dimension: str
    dimension_score: float | None = None
    coverage_ratio: float | None = None
    dimension_weight: float = 1.0


class AssessmentDetailResponse(BaseModel):
    """Full internal scorecard assessment response."""

    model_config = ConfigDict(from_attributes=True)

    assessment_id: UUID
    tenant_id: UUID
    run_id: UUID
    snapshot_id: UUID
    dq_score: float | None = None
    publication_status: str
    coverage_ratio: float | None = None
    quality_gate: str
    assessment_hash: str
    created_at: datetime
    dimension_results: list[DimensionResultResponse] = Field(default_factory=list)
    rule_results: list[CanonicalRuleResultResponse] = Field(default_factory=list)


class PublicDimensionScore(BaseModel):
    """Public projection of dimension score (zero metadata)."""

    dimension: str
    dimension_score: float | None = None
    coverage_ratio: float | None = None


class PublicAssessmentResponse(BaseModel):
    """AC-022: Public scorecard projection with 100% metadata/evidence stripped."""

    model_config = ConfigDict(from_attributes=True)

    assessment_id: UUID
    dq_score: float | None = None
    publication_status: str
    coverage_ratio: float | None = None
    quality_gate: str
    assessment_hash: str
    created_at: datetime
    dimensions: list[PublicDimensionScore] = Field(default_factory=list)
