"""Data Asset and Dataset Snapshot request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateAssetRequest(BaseModel):
    """Payload to register a new logical Data Asset."""

    name: str = Field(..., min_length=1, max_length=255)


class AssetResponse(BaseModel):
    """Data Asset response payload."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: UUID
    tenant_id: UUID
    name: str
    created_at: datetime
    format: str = "CSV"
    slug: str = ""
    current_snapshot_id: UUID | None = None
    version_count: int = 0


class SnapshotResponse(BaseModel):
    """Dataset Snapshot response payload."""

    model_config = ConfigDict(from_attributes=True)

    snapshot_id: UUID
    tenant_id: UUID
    asset_id: UUID
    source_kind: str
    source_descriptor: dict[str, Any]
    schema_definition: dict[str, Any]
    total_rows: int
    total_columns: int
    captured_at: datetime
    version_number: int | None = None
    version_status: str | None = None


class AiRecommendationRequest(BaseModel):
    """Explicit, cost-bearing request for external-LLM rule suggestions."""

    model_config = ConfigDict(extra="forbid")

    engine: Literal["LLM", "HYBRID"]
    domain: Literal["FINANCE", "RETAIL", "HEALTHCARE", "TRANSPORTATION", "GENERAL"] = "GENERAL"
    priorities: list[Literal["COMPLETENESS", "VALIDITY", "UNIQUENESS"]] = Field(min_length=1, max_length=3)
    profile_mode: Literal["SAMPLE", "FULL"] = "SAMPLE"


SemanticLabelName = Literal[
    "UNKNOWN", "IDENTIFIER", "CATEGORY", "FREE_TEXT", "QUANTITY", "MONEY",
    "DATE_TIME", "EMAIL", "PHONE", "ADDRESS", "PERSON_NAME", "BOOLEAN",
]


class SemanticInferRequest(BaseModel):
    """Explicit inference against ONE provider; endpoints and models are operator-owned."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["LOCAL", "API"]
    profile_mode: Literal["SAMPLE", "FULL"] = "SAMPLE"


class SemanticChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=1024)
    label: SemanticLabelName | None = None


class SemanticConfirmRequest(BaseModel):
    """Batch confirm (label) or reset (label null) under optimistic concurrency."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")
    changes: list[SemanticChange] = Field(min_length=1, max_length=1000)
