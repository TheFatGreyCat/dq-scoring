"""Contract tests for PostgresQueueAdapter.enqueue_run input validation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.core.entities import DatasetSnapshot, RunSpec, ScoringPolicy


def _spec(**overrides: Any) -> RunSpec:
    tenant_id = uuid4()
    snapshot = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=tenant_id,
        asset_id=uuid4(),
        source_kind="LOCAL_FILE",
        source_descriptor={"path": "/data/test.csv"},
        schema_definition={"columns": ["fare"]},
        total_rows=1,
        total_columns=1,
        captured_at=datetime.now(UTC),
    )
    return RunSpec(
        run_id=uuid4(),
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=[],
        policy=ScoringPolicy(dimension_weights={}),
        **overrides,
    )


@pytest.mark.parametrize("missing", ["ruleset_id", "policy_id", "created_by"])
def test_enqueue_run_requires_resolved_configuration(missing: str) -> None:
    spec = _spec(ruleset_id=uuid4(), policy_id=uuid4(), created_by=uuid4()).model_copy(
        update={missing: None}
    )
    queue = PostgresQueueAdapter(dsn="postgresql://unused@127.0.0.1:1/never")
    with pytest.raises(
        ValueError, match="requires spec.ruleset_id, spec.policy_id and spec.created_by"
    ):
        queue.enqueue_run(spec, idempotency_key="k")
