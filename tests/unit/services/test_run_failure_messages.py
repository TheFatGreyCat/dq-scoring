"""Regression tests: global run failures never persist raw internal exception text."""

from __future__ import annotations

from uuid import UUID

import pytest

from dq_scoring.adapters.queue.in_memory_queue import InMemoryQueueAdapter
from dq_scoring.core.entities import RunStatus
from dq_scoring.core.exceptions import RunAbortedError
from tests.unit.services.test_evaluation_orchestrator import _create_setup


class RecordingQueue(InMemoryQueueAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.errors: dict[UUID, str | None] = {}

    def complete_run(self, run_id, lease_generation, status, error_message=None, tenant_id=None):
        self.errors[run_id] = error_message
        return super().complete_run(run_id, lease_generation, status, error_message, tenant_id)


def _failing_run(exc: Exception) -> str | None:
    compute, store, _queue, _orch, spec = _create_setup()
    queue = RecordingQueue()
    from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator

    def boom(*_args, **_kwargs):
        raise exc

    compute.execute_rules = boom  # type: ignore[method-assign]
    orchestrator = EvaluationOrchestrator(compute, store, queue)
    queue.enqueue_run(spec, idempotency_key="k")
    leased = queue.claim_next_run("w")
    with pytest.raises(type(exc)):
        orchestrator.execute_leased_run(leased)
    assert queue.get_run_status(spec.run_id) == RunStatus.FAILED
    return queue.errors[spec.run_id]


def test_internal_errors_are_replaced_by_a_generic_message() -> None:
    message = _failing_run(RuntimeError("relation secret_table missing at /srv/app/internal.py line 42"))
    assert message is not None
    assert "secret_table" not in message
    assert "/srv" not in message


def test_user_actionable_run_aborts_keep_their_safe_message() -> None:
    message = _failing_run(RunAbortedError("Snapshot source changed since registration (content hash mismatch)"))
    assert message == "Snapshot source changed since registration (content hash mismatch)"
