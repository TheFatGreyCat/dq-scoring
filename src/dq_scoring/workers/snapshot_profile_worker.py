"""Serial Spark FULL work with independent heartbeats and fenced publication."""
import logging
import threading

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
from dq_scoring.common.profiling import ProfileErrorCode
from dq_scoring.common.protected_transport import protected_connect
from dq_scoring.services.snapshot_profile_service import load_snapshot

logger = logging.getLogger(__name__)


class SnapshotProfileWorker:
    def __init__(self, queue: PostgresProfileQueue, compute, heartbeat_interval: float = 5.0, monitor=None) -> None:
        self.queue, self.compute = queue, compute
        self.heartbeat_interval, self.monitor = heartbeat_interval, monitor
        self._stop = threading.Event()
        self._group = None

    def stop(self) -> None:
        self._stop.set()
        if self._group:
            self.compute.spark.sparkContext._jsc.sc().cancelJobGroupAndFutureJobs(self._group)

    def run_once(self) -> bool:
        if self._stop.is_set():
            return False
        job = self.queue.claim_next_job()
        if self.monitor:
            self.monitor.queue_available()
        if job is None:
            return False
        return self.process_job(job)

    def process_job(self, job: dict) -> bool:
        done, lost = threading.Event(), threading.Event()
        group = f"dq-profile-{job['profile_id']}-{job['lease_generation']}"
        self._group = group
        snapshot = None

        def heartbeat():
            while not done.wait(self.heartbeat_interval):
                try:
                    alive = self.queue.heartbeat(job)
                except Exception:  # noqa: BLE001 - transport failure means ownership is unproven
                    alive = False
                if not alive or self._stop.is_set():
                    lost.set()
                    self.compute.spark.sparkContext._jsc.sc().cancelJobGroupAndFutureJobs(group)
                    return

        thread = threading.Thread(target=heartbeat, name="profile-heartbeat", daemon=True)
        self.compute.spark.sparkContext.setJobGroup(group, "dq-full-profile", interruptOnCancel=True)
        if self.monitor:
            self.monitor.set_busy(True)
        thread.start()
        try:
            with protected_connect(self.queue.dsn) as conn, conn.transaction():
                set_tenant_context(conn, job["tenant_id"])
                snapshot = load_snapshot(conn, job["tenant_id"], job["snapshot_id"])
            if lost.is_set() or self._stop.is_set():
                return True
            result = self.compute.profile_snapshot(snapshot, profile_id=job["profile_id"], fingerprint=job["fingerprint"])
            if not lost.is_set() and not self._stop.is_set():
                self.queue.complete(job, result)
        except Exception as error:  # noqa: BLE001 - durable fixed-code failure, never exception text
            from typing import get_args
            code = str(error).split(":", 1)[0]
            code = code if code in get_args(ProfileErrorCode) else "PROFILE_FAILED"
            logger.warning("%s profile=%s generation=%s", code, job["profile_id"], job["lease_generation"])
            if not lost.is_set() and not self._stop.is_set():
                self.queue.fail(job, code)
        finally:
            done.set()
            thread.join(timeout=2)
            if snapshot is not None:
                self.compute.release_snapshot(snapshot)
            self.compute.spark.sparkContext.setLocalProperty("spark.jobGroup.id", None)
            self.compute.spark.sparkContext.setLocalProperty("spark.job.interruptOnCancel", None)
            self._group = None
            if self.monitor:
                self.monitor.set_busy(False)
        return True


class FairProfileScheduler:
    """Alternate successful queue classes; always try the other when the first is empty."""
    def __init__(self, evaluation, profiles: SnapshotProfileWorker | None) -> None:
        self.evaluation, self.profiles = evaluation, profiles
        self._profile_first = True

    def run_once(self) -> bool:
        if self.profiles is None:
            return self.evaluation.run_once() is not None
        order = (self.profiles, self.evaluation) if self._profile_first else (self.evaluation, self.profiles)
        for worker in order:
            self._profile_first = worker is self.evaluation
            if worker.run_once():
                return True
        return False
