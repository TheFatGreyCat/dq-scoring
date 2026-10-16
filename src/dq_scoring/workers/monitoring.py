"""Independent daemon readiness and allowlisted Spark status snapshots."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import psycopg
from botocore.exceptions import BotoCoreError, ClientError

from dq_scoring.adapters.db.postgres_worker_monitor_store import (
    PostgresWorkerMonitorStore,
)

MONITOR_INTERVAL_SECONDS = 5
MONITOR_STALE_AFTER_SECONDS = 20
MONITOR_VISIBLE_AGE_SECONDS = 86400
logger = logging.getLogger(__name__)


def infrastructure_error_code(error: Exception) -> str:
    if getattr(error, "sqlstate", None) in ("28P01", "28000"):
        return "DB_AUTH_FAILED"
    if isinstance(error, psycopg.OperationalError):
        return "DB_UNAVAILABLE"
    if isinstance(error, (BotoCoreError, ClientError)):
        return "STORAGE_UNAVAILABLE"
    return "INFRASTRUCTURE_ERROR"


class WorkerMonitor:
    def __init__(
        self,
        dsn: str,
        worker_id: str,
        kind: Literal["IMPORT", "EVALUATION"],
        metrics_supplier: Callable[[], dict[str, Any]] | None = None,
    ):
        self._dsn, self._worker_id, self._kind = dsn, worker_id, kind
        self._supplier = metrics_supplier
        self._started_at = datetime.now(UTC)
        self._lock = threading.Lock()
        self._ready = self._busy = False
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="worker-monitor", daemon=True
        )
        self._thread.start()

    def set_state(
        self, *, ready: bool, busy: bool, last_error_code: str | None = None
    ) -> None:
        with self._lock:
            self._ready, self._busy, self._error = ready, busy, last_error_code

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            self._busy = busy

    def queue_available(self) -> None:
        with self._lock:
            self._ready, self._error = True, None

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                metrics = self._supplier() if self._supplier else {}
                with self._lock:
                    ready, busy, error = self._ready, self._busy, self._error
                PostgresWorkerMonitorStore.write_snapshot(
                    self._dsn,
                    worker_id=self._worker_id,
                    kind=self._kind,
                    started_at=self._started_at,
                    ready=ready,
                    busy=busy,
                    last_error_code=error,
                    metrics=metrics,
                )
            except Exception as error:  # noqa: BLE001
                logger.warning("MONITOR_WRITE_FAILED %s", type(error).__name__)
            self._stop.wait(MONITOR_INTERVAL_SECONDS)


def spark_metrics(
    compute: Any, settings: Any, master_url: str | None = None
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "mode": "STANDALONE"
        if settings.master.startswith("spark://")
        else "KUBERNETES"
        if settings.master.startswith("k8s://")
        else "LOCAL",
        "sizing": {
            key: getattr(settings, key)
            for key in (
                "driver_memory",
                "executor_memory",
                "executor_instances",
                "executor_cores",
                "max_memory_mb",
                "sql_shuffle_partitions",
            )
        },
        "spark_status": "unknown",
        "master_status": "unknown",
    }
    try:
        spark = compute._spark
        tracker = spark.sparkContext.statusTracker()
        executors = []
        iterator = (
            spark.sparkContext._jsc.sc().statusStore().executorList(True).iterator()
        )
        while iterator.hasNext():
            executor = iterator.next()
            if executor.id() != "driver":
                executors.append(
                    {
                        "id": executor.id(),
                        "active": executor.isActive(),
                        "cores": executor.totalCores(),
                        "active_tasks": executor.activeTasks(),
                        "completed_tasks": executor.completedTasks(),
                    }
                )
        metrics.update(
            application_id=spark.sparkContext.applicationId,
            executors=executors,
            active_jobs=len(tracker.getActiveJobsIds()),
            active_stages=len(tracker.getActiveStageIds()),
            spark_status="up",
        )
    except Exception as error:  # noqa: BLE001
        logger.warning("SPARK_STATUS_UNKNOWN %s", type(error).__name__)
    if master_url:
        try:
            with (
                httpx.Client(timeout=1, follow_redirects=False) as client,
                client.stream("GET", master_url.rstrip("/") + "/json/") as response,
            ):
                response.raise_for_status()
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 1048576:
                        raise ValueError("oversized master response")
                import json

                workers = json.loads(payload)["workers"]
                metrics["workers"] = [
                    {
                        key: worker[key]
                        for key in (
                            "id",
                            "state",
                            "cores",
                            "coresused",
                            "memory",
                            "memoryused",
                        )
                    }
                    for worker in workers
                ]
                metrics["master_status"] = "up"
        except Exception as error:  # noqa: BLE001
            logger.warning("MASTER_STATUS_UNKNOWN %s", type(error).__name__)
    return metrics
