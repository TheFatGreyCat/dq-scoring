"""Data Asset and Dataset Snapshot request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
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
