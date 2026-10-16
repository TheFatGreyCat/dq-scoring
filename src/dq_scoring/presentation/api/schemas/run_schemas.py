"""Evaluation Run request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TriggerRunRequest(BaseModel):
    """Payload to trigger an asynchronous evaluation run."""

    snapshot_id: UUID
    ruleset_id: UUID
    policy_id: UUID
    execution_profile: str = "standard"
    outlier_columns: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


def safe_run_error(value: str | None) -> str | None:
    if value is None:
        return None
    prefix = value.split(":", 1)[0]
    return prefix if prefix in {"OBJECT_CHANGED", "STORAGE_UNAVAILABLE", "RESOURCE_NOT_FOUND", "CONFIGURATION_NOT_APPROVED"} else "RUN_EXECUTION_FAILED"


class RunResponse(BaseModel):
    """Evaluation Run response payload."""

    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    tenant_id: UUID
    snapshot_id: UUID
    ruleset_id: UUID
    policy_id: UUID
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    assessment_id: UUID | None = None
    _safe_error = field_validator("error_message", mode="before")(safe_run_error)


class RunStatusResponse(BaseModel):
    """Evaluation Run status polling response payload."""

    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    status: str
    error_message: str | None = None
    assessment_id: UUID | None = None
    updated_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    attempt_count: int
    _safe_error = field_validator("error_message", mode="before")(safe_run_error)
