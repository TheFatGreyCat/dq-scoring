"""Value-free, versioned profiling evidence shared by API and compute workers."""
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILER_VERSION = "full-v1"
MAX_PROFILE_BYTES = 2 * 1024 * 1024
ProfileMode = Literal["SAMPLE", "FULL"]
ProfileState = Literal["QUEUED", "RUNNING", "COMPLETE", "FAILED"]
ProfileErrorCode = Literal[
    "PROFILE_FAILED", "OBJECT_CHANGED", "STORAGE_UNAVAILABLE", "SNAPSHOT_REIMPORT_REQUIRED",
    "PROFILE_SCHEMA_MISMATCH", "PROFILE_ROW_COUNT_MISMATCH", "PROFILE_RESULT_INVALID",
]


class ColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=1024)
    technical_type: str = Field(min_length=1, max_length=64)
    null_count: int = Field(ge=0)
    non_null_count: int = Field(ge=0)
    distinct_count: int | None = Field(default=None, ge=0)
    distinct_reason: Literal["UNSUPPORTED_TYPE"] | None = None
    parse_success_count: int | None = Field(default=None, ge=0)
    parse_target: Literal["INTEGER", "DOUBLE", "DATE", "TIMESTAMP", "BOOLEAN"] | None = None
    parse_format: str | None = Field(default=None, max_length=128)
    parse_reason: Literal["NO_EXPLICIT_TARGET", "UNSUPPORTED_TYPE"] | None = None

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if self.distinct_count is None and self.distinct_reason is None:
            raise ValueError("DISTINCT_REASON_REQUIRED")
        if self.distinct_count is not None and (self.distinct_count > self.non_null_count or self.distinct_reason):
            raise ValueError("DISTINCT_COUNT_INVALID")
        if self.parse_success_count is None:
            if self.parse_reason is None:
                raise ValueError("PARSE_REASON_REQUIRED")
        elif self.parse_success_count > self.non_null_count or self.parse_target is None or self.parse_reason:
            raise ValueError("PARSE_COUNT_INVALID")
        return self


class SnapshotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: ProfileMode
    profiler_version: str = Field(min_length=1, max_length=64)
    profile_id: UUID | None = None
    fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    generated_at: datetime
    total_rows: int = Field(ge=0)
    scanned_rows: int = Field(ge=0)
    is_sample: bool
    sampling_method: Literal["PREFIX", "EXACT"]
    columns: tuple[ColumnProfile, ...] = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.scanned_rows > self.total_rows or len({c.name for c in self.columns}) != len(self.columns):
            raise ValueError("PROFILE_SCOPE_INVALID")
        if any(c.null_count + c.non_null_count != self.scanned_rows for c in self.columns):
            raise ValueError("PROFILE_COUNTS_INVALID")
        if self.mode == "FULL" and (
            self.profile_id is None or self.fingerprint is None or self.is_sample
            or self.sampling_method != "EXACT" or self.scanned_rows != self.total_rows
        ):
            raise ValueError("FULL_PROFILE_SCOPE_INVALID")
        if self.mode == "SAMPLE" and (not self.is_sample or self.sampling_method != "PREFIX"):
            raise ValueError("SAMPLE_PROFILE_SCOPE_INVALID")
        if len(self.model_dump_json().encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError("PROFILE_RESULT_TOO_LARGE")
        return self


class ProfileRequiredError(Exception):
    """Queue-domain error; presentation maps it to HTTP without coupling this boundary."""
    code = "FULL_PROFILE_REQUIRED"

    def __init__(self, job: dict | None) -> None:
        super().__init__(self.code)
        self.job = job
