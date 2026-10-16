"""Abstract queue port for asynchronous run coordination and lease fencing."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from dq_scoring.core.entities import LeasedRun, RunSpec, RunStatus


@runtime_checkable
class IQueuePort(Protocol):
    """Abstract port for asynchronous run coordination, lease acquisition, and heartbeats."""

    def enqueue_run(self, spec: RunSpec, idempotency_key: str) -> UUID:
        """Enqueue an evaluation run with idempotency deduplication."""
        ...

    def claim_next_run(
        self, worker_id: str, timeout_seconds: int = 300, run_id: UUID | None = None
    ) -> LeasedRun | None:
        """Claim the next available queued or expired run (or only run_id), updating lease generation."""
        ...

    def heartbeat(
        self,
        run_id: UUID,
        lease_generation: int,
        timeout_seconds: int | None = None,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Record worker heartbeat, ensuring lease has not been reclaimed."""
        ...

    def complete_run(
        self,
        run_id: UUID,
        lease_generation: int,
        status: RunStatus,
        error_message: str | None = None,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Mark evaluation run as terminal (SUCCEEDED, FAILED, CANCELLED) fenced by lease."""
        ...

    def get_run_status(
        self, run_id: UUID, tenant_id: UUID | None = None
    ) -> RunStatus | None:
        """Retrieve current lifecycle status for an evaluation run."""
        ...
