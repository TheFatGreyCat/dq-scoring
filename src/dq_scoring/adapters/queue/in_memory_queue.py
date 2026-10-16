"""In-memory queue adapter providing monotonic lease fencing and idempotency."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from dq_scoring.core.entities import LeasedRun, RunSpec, RunStatus
from dq_scoring.ports.queue_port import IQueuePort


class InMemoryQueueAdapter(IQueuePort):
    """In-memory queue for run dispatching, lease claiming, and heartbeats."""

    def __init__(self) -> None:
        self._runs: dict[UUID, RunSpec] = {}
        self._statuses: dict[UUID, RunStatus] = {}
        self._idempotency_map: dict[str, UUID] = {}
        self._lease_generations: dict[UUID, int] = {}
        self._queue: list[UUID] = []
        self._active_leases: dict[UUID, LeasedRun] = {}

    def enqueue_run(self, spec: RunSpec, idempotency_key: str) -> UUID:
        """Enqueue run idempotently, returning existing run_id if previously seen."""
        if idempotency_key in self._idempotency_map:
            return self._idempotency_map[idempotency_key]

        self._runs[spec.run_id] = spec
        self._statuses[spec.run_id] = RunStatus.QUEUED
        self._lease_generations[spec.run_id] = 0
        self._idempotency_map[idempotency_key] = spec.run_id
        self._queue.append(spec.run_id)
        return spec.run_id

    def claim_next_run(
        self, worker_id: str, timeout_seconds: int = 300, run_id: UUID | None = None
    ) -> LeasedRun | None:
        """Claim the next queued run (or only run_id), advancing monotonic lease generation."""
        if run_id is None:
            if not self._queue:
                return None
            run_id = self._queue.pop(0)
        elif run_id in self._queue:
            self._queue.remove(run_id)
        else:
            return None
        spec = self._runs[run_id]
        new_gen = self._lease_generations.get(run_id, 0) + 1
        self._lease_generations[run_id] = new_gen
        self._statuses[run_id] = RunStatus.RUNNING

        now = datetime.now(UTC)
        leased = LeasedRun(
            run_id=run_id,
            worker_id=worker_id,
            lease_generation=new_gen,
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=timeout_seconds),
            spec=spec,
        )
        self._active_leases[run_id] = leased
        return leased

    def heartbeat(
        self,
        run_id: UUID,
        lease_generation: int,
        timeout_seconds: int | None = None,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Verify lease generation match and extend worker lease."""
        if tenant_id is not None:
            spec = self._runs.get(run_id)
            if spec and spec.tenant_id != tenant_id:
                return False
        current_gen = self._lease_generations.get(run_id)
        if (
            current_gen is None
            or lease_generation > current_gen
            and run_id not in self._active_leases
        ):
            self._lease_generations[run_id] = lease_generation
            current_gen = lease_generation

        if current_gen != lease_generation:
            return False
        leased = self._active_leases.get(run_id)
        if leased:
            now = datetime.now(UTC)
            if leased.lease_expires_at <= now:
                return False
            ttl = timeout_seconds if timeout_seconds is not None else 300
            self._active_leases[run_id] = LeasedRun(
                run_id=leased.run_id,
                worker_id=leased.worker_id,
                lease_generation=leased.lease_generation,
                claimed_at=leased.claimed_at,
                lease_expires_at=now + timedelta(seconds=ttl),
                spec=leased.spec,
            )
        return True

    def complete_run(
        self,
        run_id: UUID,
        lease_generation: int,
        status: RunStatus,
        error_message: str | None = None,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Complete evaluation run fenced by monotonic lease generation."""
        if tenant_id is not None:
            spec = self._runs.get(run_id)
            if spec and spec.tenant_id != tenant_id:
                return False
        current_gen = self._lease_generations.get(run_id)
        if (
            current_gen is None
            or lease_generation > current_gen
            and run_id not in self._active_leases
        ):
            self._lease_generations[run_id] = lease_generation
            current_gen = lease_generation

        if current_gen != lease_generation:
            return False
        self._statuses[run_id] = status
        self._active_leases.pop(run_id, None)
        return True

    def get_run_status(
        self, run_id: UUID, tenant_id: UUID | None = None
    ) -> RunStatus | None:
        """Get current status of a run, optionally verifying tenant ownership."""
        if tenant_id is not None:
            spec = self._runs.get(run_id)
            if spec and spec.tenant_id != tenant_id:
                return None
        return self._statuses.get(run_id)
