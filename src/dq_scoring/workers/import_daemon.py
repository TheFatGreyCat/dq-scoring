"""Import and privacy-scan worker daemon polling loop running under dq_worker_role."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_import_settings, get_s3_settings
from dq_scoring.common.protected_transport import (
    protected_connect,
    require_protected_dsn,
    validate_protected_runtime,
)
from dq_scoring.workers.import_worker import ImportWorker
from dq_scoring.workers.monitoring import WorkerMonitor, infrastructure_error_code
from dq_scoring.workers.privacy_scan_worker import PrivacyScanWorker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("dq_scoring.workers.import_daemon")


class ImportDaemon:
    """Daemon executing continuous import polling and background heartbeats."""

    def __init__(self, dsn: str | None = None, worker_id: str | None = None) -> None:
        validate_protected_runtime("import")
        self.dsn = dsn or os.environ.get("DQ_WORKER_POSTGRES_DSN", "")
        if not self.dsn:
            raise ValueError("DQ_WORKER_POSTGRES_DSN must be set")
        self.dsn = require_protected_dsn(self.dsn)
        self.worker_id = worker_id or f"import-daemon-{os.getpid()}"
        self.running = False
        self._store = S3ObjectStoreAdapter(settings=get_s3_settings())
        self._worker = ImportWorker(store=self._store, worker_id=self.worker_id)
        self._privacy_worker = PrivacyScanWorker(store=self._store, worker_id=self.worker_id)
        self._privacy_first = False
        self._import_settings = get_import_settings()
        self._monitor = WorkerMonitor(
            self.dsn,
            self.worker_id,
            "IMPORT",
            metrics_supplier=lambda: {
                "sizing": {
                    key: getattr(self._import_settings, key)
                    for key in ("max_bytes", "part_bytes", "max_columns")
                }
            },
        )

    def run_once(self) -> bool:
        """Process one job, alternating which queue is tried first; falls back to the other queue.

        Returns True if a job was processed.
        """
        order = (self._run_import, self._run_privacy)
        if self._privacy_first:
            order = order[::-1]
        self._privacy_first = not self._privacy_first
        return any(attempt() for attempt in order)

    def _run_with_heartbeat(self, label: str, job_id: UUID, beat, process) -> None:
        """Run `process` while a separate-connection thread extends the lease until it finishes."""
        stop_heartbeat = threading.Event()

        def _heartbeat_loop():
            hb_interval = self._import_settings.heartbeat_seconds
            while not stop_heartbeat.wait(timeout=hb_interval):
                try:
                    with protected_connect(self.dsn, autocommit=True) as hb_conn:
                        if not beat(hb_conn):
                            logger.warning("Heartbeat failed for %s %s; lease lost", label, job_id)
                            break
                except (psycopg.Error, OSError):
                    logger.error("%s heartbeat storage failure for %s", label, job_id)

        hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        hb_thread.start()
        try:
            self._monitor.set_busy(True)
            process()
        finally:
            self._monitor.set_busy(False)
            stop_heartbeat.set()
            hb_thread.join(timeout=2.0)

    def _run_import(self) -> bool:
        with protected_connect(self.dsn, autocommit=True) as conn:
            with conn.transaction():
                session = self._worker.claim_next_session(conn)
            if not session:
                return False

            upload_id: UUID = session["upload_id"]
            lease_gen: int = session["lease_generation"]
            logger.info(
                "Claimed session %s (lease generation %d)", upload_id, lease_gen
            )

            def _process() -> None:
                with conn.transaction():
                    self._worker.process_session(conn, session)

            self._run_with_heartbeat(
                "import",
                upload_id,
                lambda hb: self._worker.heartbeat(hb, upload_id, lease_gen),
                _process,
            )
            return True

    def _run_privacy(self) -> bool:
        # Autocommit connection: the worker opens short transactions itself, so no transaction spans object I/O.
        with protected_connect(self.dsn, autocommit=True) as conn:
            job = self._privacy_worker.claim_next_job(conn)
            if not job:
                return False

            scan_id: UUID = job["scan_id"]
            logger.info(
                "Claimed privacy scan %s (lease generation %d)", scan_id, job["lease_generation"]
            )
            self._run_with_heartbeat(
                "privacy scan",
                scan_id,
                lambda hb: self._privacy_worker.heartbeat(
                    hb, scan_id, job["lease_generation"], tenant_id=job["tenant_id"]
                ),
                lambda: self._privacy_worker.process_job(conn, job),
            )
            return True

    def start(self) -> None:
        """Continuous execution loop until SIGINT/SIGTERM."""
        self.running = True

        def _handle_signal(signum, frame):
            logger.info("Received termination signal %s; shutting down...", signum)
            self.running = False

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        self._monitor.start()
        try:
            while self.running:
                try:
                    processed = self.run_once()
                    self._monitor.queue_available()
                    if not processed:
                        time.sleep(1.0)
                except (psycopg.Error, BotoCoreError, ClientError, OSError) as error:
                    code = infrastructure_error_code(error)
                    self._monitor.set_state(
                        ready=False, busy=False, last_error_code=code
                    )
                    logger.error(
                        "%s %s sqlstate=%s",
                        code,
                        type(error).__name__,
                        getattr(error, "sqlstate", None),
                    )
                    time.sleep(2.0)
        finally:
            self._monitor.stop()
        logger.info("Import daemon cleanly stopped.")


def main() -> None:
    daemon = ImportDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
