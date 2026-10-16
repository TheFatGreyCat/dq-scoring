"""Scoring Policy request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dq_scoring.core.models import StandardDimension


class CreatePolicyRequest(BaseModel):
    """Payload to create a new Scoring Policy."""

    name: str = Field(..., min_length=1, max_length=255)
    gate_fail_threshold: float = Field(default=60.0, ge=0.0, le=100.0)
    gate_warn_threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    min_coverage_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    critical_acceptance_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    dimension_weights: dict[str, float] = Field(default_factory=dict)

    @field_validator("dimension_weights")
    @classmethod
    def _canonical_dimension_weights(cls, weights: dict[str, float]) -> dict[str, float]:
        """Normalize keys to canonical dimension names; reject unknown names and negative weights."""
        allowed = {d.value for d in StandardDimension}
        normalized: dict[str, float] = {}
        for key, weight in weights.items():
            name = key.strip().upper()
            if name not in allowed:
                raise ValueError(f"Unknown dimension '{key}'. Allowed: {sorted(allowed)}")
            if weight < 0:
                raise ValueError(f"Weight for '{name}' must be >= 0")
            normalized[name] = weight
        return normalized

    @model_validator(mode="after")
    def _threshold_order(self) -> CreatePolicyRequest:
        if self.gate_fail_threshold > self.gate_warn_threshold:
            raise ValueError("gate_fail_threshold must not exceed gate_warn_threshold")
        return self


class PolicyResponse(BaseModel):
    """Scoring Policy response schema."""

    model_config = ConfigDict(from_attributes=True)

    policy_id: UUID
    tenant_id: UUID
    name: str
    status: str
    current_version: int
    gate_fail_threshold: float
    gate_warn_threshold: float
    min_coverage_threshold: float
    critical_acceptance_threshold: float | None = None
    created_by: UUID
    created_at: datetime
    dimension_weights: dict[str, float] = Field(default_factory=dict)


class SubmitPolicyRequest(BaseModel):
    """Payload to submit policy revision for approval."""

    notes: str | None = None


class ApprovePolicyRequest(BaseModel):
    """Payload to approve policy revision."""

    approval_notes: str | None = None
