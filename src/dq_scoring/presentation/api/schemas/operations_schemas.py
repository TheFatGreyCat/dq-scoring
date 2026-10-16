"""Allowlisted deployment telemetry contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ComponentStatus = Literal["up", "down", "degraded", "unknown"]


class ExecutorMetrics(BaseModel):
    id: str
    active: bool
    cores: int = Field(ge=0)
    active_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)


class SparkSizing(BaseModel):
    driver_memory: str
    executor_memory: str
    executor_instances: int = Field(ge=1)
    executor_cores: int = Field(ge=1)
    max_memory_mb: int = Field(ge=1)
    sql_shuffle_partitions: int = Field(ge=1)


class MasterWorker(BaseModel):
    id: str
    state: str
    cores: int = Field(ge=0)
    coresused: int = Field(ge=0)
    memory: int = Field(ge=0)
    memoryused: int = Field(ge=0)


class SnapshotMetrics(BaseModel):
    mode: Literal["LOCAL", "STANDALONE", "KUBERNETES"] | None = None
    application_id: str | None = None
    spark_status: ComponentStatus = "unknown"
    master_status: ComponentStatus = "unknown"
    sizing: SparkSizing | None = None
    executors: list[ExecutorMetrics] | None = None
    workers: list[MasterWorker] | None = None
    active_jobs: int | None = Field(default=None, ge=0)
    active_stages: int | None = Field(default=None, ge=0)


class WorkerSnapshot(BaseModel):
    worker_id: str
    kind: Literal["IMPORT", "EVALUATION"]
    started_at: datetime
    heartbeat_at: datetime
    status: Literal["initializing", "ready", "busy", "degraded", "stale"]
    last_error_code: (
        Literal[
            "DB_AUTH_FAILED",
            "DB_UNAVAILABLE",
            "STORAGE_UNAVAILABLE",
            "INFRASTRUCTURE_ERROR",
        ]
        | None
    ) = None
    metrics: SnapshotMetrics


class Components(BaseModel):
    api: Literal["up"] = "up"
    database: ComponentStatus = "unknown"
    storage: ComponentStatus = "unknown"
    spark_master: ComponentStatus = "unknown"


class QueueSummary(BaseModel):
    queued: int | None = None
    active: int | None = None
    failed_24h: int | None = None
    oldest_queued_at: datetime | None = None


class SparkSummary(BaseModel):
    mode: str | None = None
    expected_executors: int | None = None
    active_executors: int | None = None
    workers: list[dict] = Field(default_factory=list)
    active_jobs: int | None = None
    active_stages: int | None = None


class MonitorResponse(BaseModel):
    checked_at: datetime
    components: Components
    workers: list[WorkerSnapshot]
    spark: SparkSummary
    queue: QueueSummary
    warnings: list[str] = Field(default_factory=list)
