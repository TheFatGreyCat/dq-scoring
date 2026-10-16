"""Evaluation Worker Daemon entrypoint for Kubernetes / containerized execution."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from uuid import uuid4

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.common.protected_transport import (
    ProtectedTransportError,
    require_protected_dsn,
    validate_protected_runtime,
)
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker
from dq_scoring.workers.monitoring import (
    WorkerMonitor,
    infrastructure_error_code,
    spark_metrics,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(threadName)s): %(message)s",
)
logger = logging.getLogger("dq_scoring.worker_daemon")


def run_daemon() -> None:
    """Run worker daemon until interrupted by SIGINT / SIGTERM."""
    dsn = os.getenv("DQ_WORKER_POSTGRES_DSN")
    if not dsn:
        sys.exit("DQ_WORKER_POSTGRES_DSN is required; refusing to start without it.")
    try:
        validate_protected_runtime("worker")
        dsn = require_protected_dsn(dsn)
    except ProtectedTransportError as error:
        logger.error("Worker configuration error: %s", error)
        sys.exit(1)
    worker_id = (
        os.getenv("DQ_WORKER_ID") or f"worker-{os.getenv('HOSTNAME', uuid4().hex[:8])}"
    )
    poll_interval = float(os.getenv("DQ_WORKER_POLL_INTERVAL", "1.0"))
    heartbeat_interval = float(os.getenv("DQ_WORKER_HEARTBEAT_INTERVAL", "5.0"))

    compute = None
    monitor = WorkerMonitor(
        dsn,
        worker_id,
        "EVALUATION",
        metrics_supplier=lambda: (
            spark_metrics(
                compute, compute.settings, os.getenv("DQ_SPARK_MASTER_UI_URL")
            )
            if compute is not None
            else {"spark_status": "unknown"}
        ),
    )
    monitor.start()
    try:
        store = PostgresAssessmentStoreAdapter(dsn=dsn)
        queue = PostgresQueueAdapter(dsn=dsn)
        compute = PySparkComputeAdapter()
        orchestrator = EvaluationOrchestrator(
            compute_engine=compute, assessment_store=store, queue_port=queue
        )
        worker = EvaluationWorker(
            queue_port=queue,
            orchestrator=orchestrator,
            worker_id=worker_id,
            poll_interval=poll_interval,
            heartbeat_interval=heartbeat_interval,
            on_busy_changed=monitor.set_busy,
            on_queue_available=monitor.queue_available,
        )

        def _signal_handler(signum: int, _frame: object) -> None:
            logger.info("Received termination signal %s", signum)
            worker.stop()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        while not worker._stop_event.is_set():
            try:
                assessment = worker.run_once()
                if assessment:
                    logger.info(
                        "Successfully processed run %s -> Assessment %s",
                        assessment.run_id,
                        assessment.assessment_id,
                    )
                else:
                    time.sleep(poll_interval)
            except Exception as error:  # noqa: BLE001
                code = infrastructure_error_code(error)
                monitor.set_state(ready=False, busy=False, last_error_code=code)
                logger.error(
                    "%s %s sqlstate=%s",
                    code,
                    type(error).__name__,
                    getattr(error, "sqlstate", None),
                )
                time.sleep(poll_interval)
    finally:
        monitor.stop()
        if compute is not None:
            compute.spark.stop()


if __name__ == "__main__":
    run_daemon()
