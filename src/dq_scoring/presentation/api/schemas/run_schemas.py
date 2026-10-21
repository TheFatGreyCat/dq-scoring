"""Evaluation Run request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TriggerRunRequest(BaseModel):
    """Payload to trigger an asynchronous evaluation run."""

    snapshot_id: UUID
    ruleset_id: UUID
    policy_id: UUID
    execution_profile: str = "standard"
    outlier_columns: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    reuse_completed: bool = True


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
    created_by: UUID | None = None
    owned_by_me: bool = False
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
    created_by: UUID | None = None
    owned_by_me: bool = False
    _safe_error = field_validator("error_message", mode="before")(safe_run_error)


RUN_EVENT_TYPES = frozenset({"RUN_QUEUED", "RUN_CLAIMED", "RUN_RUNNING", "RUN_SUCCEEDED", "RUN_FAILED", "RUN_CANCELLED"})


class RunEventResponse(BaseModel):
    """Allowlisted projection of run_events; raw event_payload is never exposed."""

    event_id: UUID
    event_type: str
    attempt_count: int
    lease_generation: int | None = None
    created_at: datetime
    error_code: str | None = None

    @model_validator(mode="after")
    def _allowlist(self) -> RunEventResponse:
        if self.event_type not in RUN_EVENT_TYPES:
            self.event_type = "RUN_EVENT"
        if self.event_type != "RUN_FAILED":
            self.error_code = None
        else:
            self.error_code = safe_run_error(self.error_code)
        return self


class RunEventPage(BaseModel):
    items: list[RunEventResponse]
    next_cursor: str | None = None
