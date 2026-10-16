"""Pydantic schemas for MinIO dataset imports and storage browsing."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DISALLOWED_FILENAME_CHARS = re.compile(r"[\x00-\x1f\x7f\\/]")


class SourceObject(BaseModel):
    """Reference to an existing object in storage to be staged."""

    model_config = ConfigDict(frozen=True)

    bucket: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=1024)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if any(part in ("", ".", "..") for part in v.split("/")) or "\\" in v or v.startswith("/") or "?" in v or "#" in v or "://" in v or any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise ValueError("Invalid storage object key: path traversal or query parameters not allowed")
        return v


class CsvOptions(BaseModel):
    """Parsing options for CSV uploads."""

    model_config = ConfigDict(frozen=True)

    delimiter: str = Field(default=",", min_length=1, max_length=1)
    encoding: str = Field(default="utf-8")

    @field_validator("delimiter")
    @classmethod
    def validate_delimiter(cls, v: str) -> str:
        if v not in (",", ";", "\t", "|"):
            raise ValueError(f"Unsupported CSV delimiter '{v}'. Allowed: comma, semicolon, tab, pipe.")
        return v


class CreateImportRequest(BaseModel):
    """Payload to initiate a new dataset upload or staging import session."""

    model_config = ConfigDict(frozen=True)

    client_request_id: UUID
    asset_id: UUID | None = None
    asset_name: str | None = Field(default=None, min_length=1, max_length=255)
    format: Literal["CSV", "PARQUET", "JSONL"]
    original_filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    source: SourceObject | None = None
    csv_options: CsvOptions | None = None

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        v_stripped = v.strip()
        if not v_stripped:
            raise ValueError("Filename cannot be blank")
        if DISALLOWED_FILENAME_CHARS.search(v_stripped):
            raise ValueError("Filename contains invalid or control characters")
        return v_stripped

    @field_validator("asset_name")
    @classmethod
    def validate_asset_name(cls, v: str | None) -> str | None:
        if v is not None:
            v_stripped = v.strip()
            if not v_stripped:
                raise ValueError("Asset name cannot be blank")
            return v_stripped
        return None

    @model_validator(mode="after")
    def validate_asset_target(self) -> CreateImportRequest:
        has_id = self.asset_id is not None
        has_name = self.asset_name is not None
        if has_id == has_name:
            raise ValueError("Exactly one of asset_id or asset_name must be specified.")
        return self


class PartETag(BaseModel):
    """ETag record for an uploaded part."""

    model_config = ConfigDict(frozen=True)

    part_number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1)


class CompleteImportRequest(BaseModel):
    """Payload to complete an active multipart upload."""

    model_config = ConfigDict(frozen=True)

    parts: list[PartETag] = Field(min_length=1)


class ConfigureImportRequest(BaseModel):
    """Payload to rename or map schema columns for a verified or column-collision import."""

    model_config = ConfigDict(frozen=True)

    column_names: list[str] = Field(min_length=1, max_length=1000)

    @field_validator("column_names")
    @classmethod
    def validate_unique_nonblank(cls, v: list[str]) -> list[str]:
        cleaned = [c.strip() for c in v]
        if any(not c for c in cleaned):
            raise ValueError("Column names cannot be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Column names must be unique")
        return cleaned


class RegisterImportRequest(BaseModel):
    """Payload to finalize an import and register an immutable Dataset Snapshot."""

    model_config = ConfigDict(frozen=True)

    acknowledged_warnings: list[str] = Field(default_factory=list)


class StorageObjectItem(BaseModel):
    """Metadata item for browser storage list."""

    model_config = ConfigDict(frozen=True)

    bucket: str
    key: str
    size_bytes: int
    last_modified: datetime | None = None


class StorageObjectsResponse(BaseModel):
    """Response containing browsable storage objects."""

    model_config = ConfigDict(frozen=True)

    items: list[StorageObjectItem]
    next_token: str | None = None


class ImportSessionResponse(BaseModel):
    """Response representing an upload or import session state."""

    model_config = ConfigDict(frozen=True)

    upload_id: UUID
    status: str
    format: str
    part_size: int
    part_count: int
    size_bytes: int
    original_filename: str
    asset_id: UUID | None = None
    asset_name: str | None = None
    client_request_id: UUID | None = None
    error_code: str | None = None
    invalid_params: list[dict[str, Any]] | None = None
    warnings: list[str] | None = None
    preview: list[dict[str, Any]] | None = None
    profile: dict[str, Any] | None = None
    snapshot_id: UUID | None = None
    completed_parts: list[int] | None = None
    completed_part_details: list[dict[str, Any]] = Field(default_factory=list)
    schema_definition: dict[str, Any] = Field(default_factory=dict)
    source_descriptor: dict[str, Any] = Field(default_factory=dict)
    total_rows: int | None = None
    total_columns: int | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    csv_options: CsvOptions | None = None


class ImportSessionSummary(BaseModel):
    upload_id: UUID
    status: Literal["INITIATED", "UPLOADING", "STAGED", "VERIFYING", "VERIFIED", "REJECTED", "FAILED", "ABORTED", "REGISTERED"]
    asset_id: UUID | None = None
    asset_name: str | None = None
    format: str
    original_filename: str
    size_bytes: int
    error_code: str | None = None
    snapshot_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
