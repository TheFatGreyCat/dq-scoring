"""Bounded storage probes and infrastructure snapshot projection."""

from datetime import UTC, datetime

import boto3
from botocore.config import Config
from pydantic import ValidationError

from dq_scoring.presentation.api.schemas.operations_schemas import (
    Components,
    MonitorResponse,
    QueueSummary,
    SnapshotMetrics,
    SparkSummary,
    WorkerSnapshot,
)
from dq_scoring.workers.monitoring import MONITOR_STALE_AFTER_SECONDS


def storage_status(settings, tenant_id):
    try:
        client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key_id.get_secret_value(),
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            region_name=settings.region,
            config=Config(
                connect_timeout=1, read_timeout=1, retries={"total_max_attempts": 1}
            ),
        )
        client.list_objects_v2(
            Bucket=settings.bucket_staging, Prefix=f"imports/{tenant_id}/", MaxKeys=1
        )
        versioning = client.get_bucket_versioning(Bucket=settings.bucket_snapshots)
        return "up" if versioning.get("Status") == "Enabled" else "degraded"
    except Exception:  # noqa: BLE001
        return "down"


def monitor_snapshot(conn, tenant_id, storage):
    now = datetime.now(UTC)
    workers = []
    rows = conn.execute(
        "SELECT worker_id,kind,started_at,heartbeat_at,ready,busy,last_error_code,metrics FROM worker_monitor_snapshots WHERE heartbeat_at>=now()-interval '24 hours' ORDER BY worker_id"
    ).fetchall()
    for worker_id, kind, started, heartbeat, ready, busy, error, metrics in rows:
        try:
            parsed = (
                SnapshotMetrics.model_validate(metrics)
                if kind == "EVALUATION"
                else SnapshotMetrics()
            )
        except ValidationError:
            parsed = SnapshotMetrics()
        status = (
            "stale"
            if (now - heartbeat).total_seconds() > MONITOR_STALE_AFTER_SECONDS
            else "degraded"
            if not ready and error
            else "initializing"
            if not ready
            else "busy"
            if busy
            else "ready"
        )
        safe_error = (
            error
            if error
            in (
                "DB_AUTH_FAILED",
                "DB_UNAVAILABLE",
                "STORAGE_UNAVAILABLE",
                "INFRASTRUCTURE_ERROR",
            )
            else None
        )
        workers.append(
            WorkerSnapshot(
                worker_id=worker_id,
                kind=kind,
                started_at=started,
                heartbeat_at=heartbeat,
                status=status,
                last_error_code=safe_error,
                metrics=parsed,
            )
        )
    drivers = sorted(
        (w for w in workers if w.kind == "EVALUATION" and w.status != "stale"),
        key=lambda w: (w.heartbeat_at, w.worker_id),
        reverse=True,
    )
    spark = SparkSummary()
    master = "unknown"
    if drivers:
        metrics = drivers[0].metrics
        master = metrics.master_status
        spark = SparkSummary(
            mode=metrics.mode,
            expected_executors=metrics.sizing.executor_instances
            if metrics.sizing
            else None,
            active_executors=sum(
                e.active for e in metrics.executors if e.id != "driver"
            )
            if metrics.executors is not None
            else None,
            active_jobs=metrics.active_jobs,
            active_stages=metrics.active_stages,
            workers=[
                {
                    "id": w.id,
                    "state": w.state,
                    "cores": w.cores,
                    "allocated_cores": w.coresused,
                    "memory_mib": w.memory,
                    "allocated_memory_mib": w.memoryused,
                }
                for w in metrics.workers or []
            ],
        )
    counts = conn.execute(
        "SELECT count(*) FILTER (WHERE run_status='QUEUED'),count(*) FILTER (WHERE run_status IN ('LEASED','RUNNING')),count(*) FILTER (WHERE run_status='FAILED' AND created_at>=now()-interval '24 hours'),min(created_at) FILTER (WHERE run_status='QUEUED') FROM evaluation_runs WHERE tenant_id=%s",
        (tenant_id,),
    ).fetchone()
    return MonitorResponse(
        checked_at=now,
        components=Components(database="up", storage=storage, spark_master=master),
        workers=workers,
        spark=spark,
        queue=QueueSummary(
            queued=counts[0],
            active=counts[1],
            failed_24h=counts[2],
            oldest_queued_at=counts[3],
        ),
        warnings=["MULTIPLE_EVALUATION_DRIVERS"] if len(drivers) > 1 else [],
    )
