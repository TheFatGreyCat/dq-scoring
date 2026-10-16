"""Evaluation Worker daemon coordinating leased runs and periodic heartbeats."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from uuid import UUID

from dq_scoring.core.entities import ImmutableAssessment, LeasedRun
from dq_scoring.ports.queue_port import IQueuePort
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator

logger = logging.getLogger(__name__)


class HeartbeatController:
    """Background heartbeat updater renewing lease TTL until stopped."""

    def __init__(
        self,
        queue_port: IQueuePort,
        leased_run: LeasedRun,
        interval_seconds: float = 5.0,
        on_lease_lost: Callable[[], None] | None = None,
    ) -> None:
        self._queue = queue_port
        self._run = leased_run
        self._interval = interval_seconds
        self._on_lease_lost = on_lease_lost
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lease_lost = False

    def start(self) -> None:
        """Start background heartbeat thread."""
        self._thread = threading.Thread(
            target=self._run_heartbeat,
            name=f"heartbeat-{self._run.run_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop background heartbeat thread and join."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    @property
    def is_lease_lost(self) -> bool:
        """Return whether the lease was lost during heartbeat."""
        return self._lease_lost

    def _run_heartbeat(self) -> None:
        """Periodic loop executing heartbeat until stopped."""
        while not self._stop_event.wait(self._interval):
            success = self._queue.heartbeat(
                run_id=self._run.run_id,
                lease_generation=self._run.lease_generation,
                tenant_id=self._run.spec.tenant_id,
            )
            if not success:
                logger.warning(
                    "Heartbeat failed for run %s (gen %s) - lease lost or superseded",
                    self._run.run_id,
                    self._run.lease_generation,
                )
                self._lease_lost = True
                if self._on_lease_lost:
                    self._on_lease_lost()
                break


class EvaluationWorker:
    """Worker daemon continuously claiming and executing queued evaluation runs."""

    def __init__(
        self,
        queue_port: IQueuePort,
        orchestrator: EvaluationOrchestrator,
        worker_id: str = "eval-worker-01",
        poll_interval: float = 1.0,
        max_backoff: float = 5.0,
        heartbeat_interval: float = 5.0,
        on_busy_changed: Callable[[bool], None] | None = None,
        on_queue_available: Callable[[], None] | None = None,
    ) -> None:
        self._queue = queue_port
        self._orchestrator = orchestrator
        self.worker_id = worker_id
        self._poll_interval = poll_interval
        self._max_backoff = max_backoff
        self._heartbeat_interval = heartbeat_interval
        self._stop_event = threading.Event()
        self._on_busy_changed = on_busy_changed
        self._on_queue_available = on_queue_available

    def stop(self) -> None:
        """Signal worker to stop after completing or cancelling current job."""
        self._stop_event.set()

    def run_once(self) -> ImmutableAssessment | None:
        """Claim the next queued run and execute it under heartbeat protection."""
        leased_run = self._queue.claim_next_run(self.worker_id)
        if self._on_queue_available:
            self._on_queue_available()
        return self._execute(leased_run) if leased_run else None

    def run_by_id(self, run_id: UUID) -> ImmutableAssessment | None:
        """Claim and execute one specific run (Spark driver launched for that run)."""
        leased_run = self._queue.claim_next_run(self.worker_id, run_id=run_id)
        if self._on_queue_available:
            self._on_queue_available()
        return self._execute(leased_run) if leased_run else None

    def _execute(self, leased_run: LeasedRun) -> ImmutableAssessment:

        logger.info(
            "Worker %s claimed run %s (generation %s)",
            self.worker_id,
            leased_run.run_id,
            leased_run.lease_generation,
        )

        lease_lost = threading.Event()

        def _handle_lease_lost() -> None:
            logger.warning(
                "Worker %s detected lease loss for run %s (gen %s) during heartbeat renewal",
                self.worker_id,
                leased_run.run_id,
                leased_run.lease_generation,
            )
            lease_lost.set()

        heartbeat = HeartbeatController(
            queue_port=self._queue,
            leased_run=leased_run,
            interval_seconds=self._heartbeat_interval,
            on_lease_lost=_handle_lease_lost,
        )
        heartbeat.start()
        try:
            if self._on_busy_changed:
                self._on_busy_changed(True)
            assessment = self._orchestrator.execute_leased_run(leased_run)
            return assessment
        finally:
            heartbeat.stop()
            if self._on_busy_changed:
                self._on_busy_changed(False)

    def run_loop(self, max_iterations: int | None = None) -> int:
        """Run continuous polling loop until stopped or max_iterations reached."""
        iterations = 0
        current_sleep = self._poll_interval

        while not self._stop_event.is_set():
            if max_iterations is not None and iterations >= max_iterations:
                break

            try:
                assessment = self.run_once()
                iterations += 1

                if assessment is not None:
                    current_sleep = self._poll_interval
                else:
                    time.sleep(current_sleep)
                    current_sleep = min(current_sleep * 1.5, self._max_backoff)
            except Exception as exc:  # noqa: BLE001
                logger.error("Error during worker execution cycle: %s", exc)
                time.sleep(current_sleep)

        return iterations
