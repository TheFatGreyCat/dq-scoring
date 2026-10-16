"""Schemas for sensitive data findings and asset protection policies."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dq_scoring.presentation.api.pagination import Page


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: UUID
    column_name: str
    path: str
    category: str
    detector_code: str | None = None
    method: str | None = None
    matched_count: int | None = None
    observed_count: int | None = None
    status: Literal["DETECTED", "CONFIRMED", "DISMISSED"]
    detector_revision: str | None = None
    rule_id: UUID | None = None
    rule_revision: int | None = None
    scan_id: UUID | None = None
    historical: bool = False


class SensitiveFindingsResponse(BaseModel):
    scan_status: Literal["COMPLETE", "UNAVAILABLE", "QUEUED", "RUNNING", "FAILED"]
    detector_revision: str | None = None
    scan_stale: bool = False
    scan_id: UUID | None = None
    scanned_at: datetime | None = None
    config_version: int | None = None
    active_config_version: int | None = None
    findings: Page[FindingResponse]


class UpdateFindingStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: Literal["DETECTED", "CONFIRMED", "DISMISSED"]
    status: Literal["CONFIRMED", "DISMISSED"]
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class PolicyResponse(BaseModel):
    asset_id: UUID
    version: int
    categories: list[str]
    unsupported_policies: int


class UpdatePolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    categories: list[Literal["BASIC_PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA", "CONFIDENTIAL_BUSINESS_DATA"]] = Field(
        default_factory=list
    )


PrivacyCategory = Literal[
    "STANDARD_DATA", "BASIC_PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA", "CONFIDENTIAL_BUSINESS_DATA"
]


class ColumnClassification(BaseModel):
    column_name: str
    declared_category: PrivacyCategory | None
    detected_categories: list[PrivacyCategory]
    effective_categories: list[PrivacyCategory]
    protected: bool
    conflict: bool
    reason: str | None


class ColumnClassificationsResponse(BaseModel):
    asset_id: UUID
    snapshot_id: UUID
    version: int
    scan_status: Literal["COMPLETE", "UNAVAILABLE", "QUEUED", "RUNNING", "FAILED"]
    scan_stale: bool
    columns: list[ColumnClassification]


class ClassificationChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_name: str = Field(min_length=1)
    category: PrivacyCategory | None
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class UpdateClassificationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    expected_version: int = Field(ge=0)
    changes: list[ClassificationChange] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _reject_duplicate_columns(self) -> UpdateClassificationsRequest:
        names = [change.column_name for change in self.changes]
        if len(names) != len(set(names)):
            raise ValueError("DUPLICATE_CLASSIFICATION_COLUMN")
        return self
