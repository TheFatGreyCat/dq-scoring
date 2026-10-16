"""PostgreSQL 16 queue adapter implementing monotonic lease fencing and SKIP LOCKED dispatching."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.policy_mapping import scoring_policy_from_row
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.common.protected_transport import protected_connect
from dq_scoring.core.entities import (
    DatasetSnapshot,
    LeasedRun,
    QualityRule,
    RunSpec,
    RunStatus,
)
from dq_scoring.ports.queue_port import IQueuePort


class PostgresQueueAdapter(IQueuePort):
    """PostgreSQL 16 queue implementation with lease fencing and SKIP LOCKED claiming."""

    def __init__(
        self,
        dsn: str | None = None,
        connection: psycopg.Connection | None = None,
        lease_timeout_seconds: int = 300,
    ) -> None:
        if dsn is None and connection is None:
            raise ValueError(
                "Either dsn or connection must be provided to PostgresQueueAdapter"
            )
        self._dsn = dsn
        self._conn = connection
        self._lease_timeout_seconds = lease_timeout_seconds

    @contextmanager
    def _get_connection(self) -> Iterator[psycopg.Connection]:
        if self._conn is not None:
            yield self._conn
        else:
            assert self._dsn is not None
            with protected_connect(self._dsn) as conn:
                yield conn

    def enqueue_run(self, spec: RunSpec, idempotency_key: str) -> UUID:
        """Enqueue run idempotently, returning existing run_id if previously seen."""
        if spec.ruleset_id is None or spec.policy_id is None or spec.created_by is None:
            raise ValueError(
                "enqueue_run requires spec.ruleset_id, spec.policy_id and spec.created_by"
            )
        with self._get_connection() as conn, conn.transaction():
            set_tenant_context(conn, spec.tenant_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT run_id FROM evaluation_runs
                    WHERE tenant_id = %s AND idempotency_key = %s;
                    """,
                    (spec.tenant_id, idempotency_key),
                )
                existing = cur.fetchone()
                if existing:
                    return existing[0]

                outlier_payload: dict[str, Any] = {
                    "outlier_columns": spec.outlier_columns,
                    "_run_spec": spec.model_dump(mode="json"),
                }
                outlier_json_str = json.dumps(outlier_payload, sort_keys=True)
                outlier_hash = hashlib.sha256(
                    outlier_json_str.encode("utf-8")
                ).hexdigest()

                # ON CONFLICT closes the race between the SELECT above and a concurrent
                # retry with the same key: the loser reads back the winner's run_id.
                cur.execute(
                    """
                    INSERT INTO evaluation_runs (
                        run_id, tenant_id, snapshot_id, ruleset_id, policy_id,
                        workload_tier, trigger_type, execution_profile,
                        outlier_config, outlier_config_hash, priority,
                        run_status, attempt_count, lease_generation,
                        idempotency_key, created_by, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        'SMALL', 'ON_DEMAND', %s,
                        %s, %s, 5,
                        'QUEUED', 0, 0,
                        %s, %s, now()
                    )
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    RETURNING run_id;
                    """,
                    (
                        spec.run_id,
                        spec.tenant_id,
                        spec.snapshot.snapshot_id,
                        spec.ruleset_id,
                        spec.policy_id,
                        "SPARK_K3S"
                        if (spec.execution_profile or "").upper()
                        in ("SPARK_K3S", "STANDARD")
                        else (spec.execution_profile or "SPARK_K3S"),
                        Jsonb(outlier_payload),
                        outlier_hash,
                        idempotency_key,
                        spec.created_by,
                    ),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        "SELECT run_id FROM evaluation_runs WHERE tenant_id = %s AND idempotency_key = %s;",
                        (spec.tenant_id, idempotency_key),
                    )
                    return cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO run_events (
                        event_id, tenant_id, run_id, event_type,
                        attempt_count, lease_generation, event_payload, created_at
                    ) VALUES (
                        %s, %s, %s, 'RUN_QUEUED', 0, 0, '{}'::jsonb, now()
                    );
                    """,
                    (uuid4(), spec.tenant_id, spec.run_id),
                )

        return spec.run_id

    def claim_next_run(
        self, worker_id: str, timeout_seconds: int = 300, run_id: UUID | None = None
    ) -> LeasedRun | None:
        """Claim next queued or expired run using FOR UPDATE SKIP LOCKED and increment lease generation."""
        with (
            self._get_connection() as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            cur.execute(
                """
                WITH next_run AS (
                    SELECT run_id
                    FROM evaluation_runs
                    WHERE (run_status = 'QUEUED'
                       OR (run_status IN ('LEASED', 'RUNNING') AND lease_expires_at < now()))
                      AND (%s::uuid IS NULL OR run_id = %s::uuid)
                    ORDER BY priority ASC, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE evaluation_runs r
                SET run_status = 'LEASED',
                    lease_owner = %s,
                    lease_generation = r.lease_generation + 1,
                    lease_expires_at = now() + (%s || ' seconds')::interval,
                    started_at = COALESCE(r.started_at, now()),
                    heartbeat_at = now(),
                    attempt_count = r.attempt_count + 1
                FROM next_run
                WHERE r.run_id = next_run.run_id
                RETURNING r.run_id, r.tenant_id, r.snapshot_id, r.ruleset_id, r.policy_id,
                          r.execution_profile, r.outlier_config, r.lease_generation,
                          r.lease_expires_at, r.heartbeat_at, r.started_at, r.attempt_count;
                """,
                (run_id, run_id, worker_id, timeout_seconds),
            )
            row = cur.fetchone()
            if row is None:
                return None

            (
                run_id,
                tenant_id,
                snapshot_id,
                ruleset_id,
                policy_id,
                execution_profile,
                outlier_config,
                lease_gen,
                lease_exp,
                _heartbeat_at,
                started_at,
                attempt_count,
            ) = row

            set_tenant_context(conn, tenant_id)
            cur.execute(
                """
                INSERT INTO run_events (
                    event_id, tenant_id, run_id, event_type,
                    attempt_count, lease_generation, event_payload, created_at
                ) VALUES (
                    %s, %s, %s, 'RUN_CLAIMED', %s, %s, %s, now()
                );
                """,
                (
                    uuid4(),
                    tenant_id,
                    run_id,
                    attempt_count,
                    lease_gen,
                    Jsonb({"worker_id": worker_id}),
                ),
            )

            spec_data = (
                outlier_config.get("_run_spec")
                if isinstance(outlier_config, dict)
                else None
            )
            if spec_data:
                spec = RunSpec.model_validate(spec_data)
            else:
                spec = self._reconstruct_spec(
                    conn,
                    run_id,
                    tenant_id,
                    snapshot_id,
                    ruleset_id,
                    policy_id,
                    execution_profile,
                    outlier_config,
                )

            return LeasedRun(
                run_id=run_id,
                worker_id=worker_id,
                lease_generation=lease_gen,
                claimed_at=started_at or datetime.now(UTC),
                lease_expires_at=lease_exp,
                spec=spec,
            )

    def heartbeat(
        self,
        run_id: UUID,
        lease_generation: int,
        timeout_seconds: int | None = None,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Extend lease and update heartbeat_at atomically if lease generation matches and has not expired."""
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._lease_timeout_seconds
        )
        with (
            self._get_connection() as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            if tenant_id is not None:
                set_tenant_context(conn, tenant_id)
            else:
                cur.execute(
                    "SELECT tenant_id FROM evaluation_runs WHERE run_id = %s;",
                    (run_id,),
                )
                row = cur.fetchone()
                if row:
                    set_tenant_context(conn, row[0])

            cur.execute(
                """
                UPDATE evaluation_runs
                SET heartbeat_at = now(),
                    lease_expires_at = now() + (%s || ' seconds')::interval
                WHERE run_id = %s
                  AND lease_generation = %s
                  AND run_status IN ('LEASED', 'RUNNING')
                  AND lease_expires_at > now();
                """,
                (effective_timeout, run_id, lease_generation),
            )
            return cur.rowcount == 1

    def complete_run(
        self,
        run_id: UUID,
        lease_generation: int,
        status: RunStatus,
        error_message: str | None = None,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Mark run completion fenced by monotonic lease generation and active TTL."""
        with (
            self._get_connection() as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            if tenant_id is not None:
                set_tenant_context(conn, tenant_id)
            else:
                cur.execute(
                    "SELECT tenant_id FROM evaluation_runs WHERE run_id = %s;",
                    (run_id,),
                )
                row = cur.fetchone()
                if row:
                    set_tenant_context(conn, row[0])

            cur.execute(
                """
                UPDATE evaluation_runs
                SET run_status = %s,
                    completed_at = now(),
                    execution_error = %s
                WHERE run_id = %s
                  AND lease_generation = %s
                  AND run_status IN ('LEASED', 'RUNNING')
                  AND (lease_expires_at IS NULL OR lease_expires_at > now());
                """,
                (status.value, error_message, run_id, lease_generation),
            )
            if cur.rowcount == 1:
                cur.execute(
                    "SELECT tenant_id, attempt_count FROM evaluation_runs WHERE run_id = %s;",
                    (run_id,),
                )
                row = cur.fetchone()
                if row:
                    t_id, att_cnt = row
                    set_tenant_context(conn, t_id)
                    event_type = f"RUN_{status.value}"
                    cur.execute(
                        """
                        INSERT INTO run_events (
                            event_id, tenant_id, run_id, event_type,
                            attempt_count, lease_generation, event_payload, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, now()
                        );
                        """,
                        (
                            uuid4(),
                            t_id,
                            run_id,
                            event_type,
                            att_cnt,
                            lease_generation,
                            Jsonb({"error": error_message} if error_message else {}),
                        ),
                    )
                return True

            cur.execute(
                "SELECT run_status, lease_generation FROM evaluation_runs WHERE run_id = %s;",
                (run_id,),
            )
            row = cur.fetchone()
            return bool(row and row[0] == status.value and row[1] == lease_generation)

    def get_run_status(
        self, run_id: UUID, tenant_id: UUID | None = None
    ) -> RunStatus | None:
        """Retrieve current lifecycle status for an evaluation run."""
        with self._get_connection() as conn, conn.cursor() as cur:
            if tenant_id is not None:
                set_tenant_context(conn, tenant_id)
                cur.execute(
                    "SELECT run_status FROM evaluation_runs WHERE run_id = %s AND tenant_id = %s;",
                    (run_id, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT run_status FROM evaluation_runs WHERE run_id = %s;",
                    (run_id,),
                )
            row = cur.fetchone()
            if row:
                return RunStatus(row[0])
            return None

    def _reconstruct_spec(
        self,
        conn: psycopg.Connection,
        run_id: UUID,
        tenant_id: UUID,
        snapshot_id: UUID,
        ruleset_id: UUID,
        policy_id: UUID,
        execution_profile: str,
        outlier_config: dict[str, Any],
    ) -> RunSpec:
        """Fallback reconstruction of RunSpec from database tables."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_id, source_kind, source_descriptor, schema_definition,
                       total_rows, total_columns, captured_at
                FROM dataset_snapshots WHERE tenant_id = %s AND snapshot_id = %s;
                """,
                (tenant_id, snapshot_id),
            )
            s_row = cur.fetchone()
            assert s_row is not None, f"Snapshot {snapshot_id} not found"
            snapshot = DatasetSnapshot(
                snapshot_id=snapshot_id,
                tenant_id=tenant_id,
                asset_id=s_row[0],
                source_kind=s_row[1],
                source_descriptor=s_row[2] or {},
                schema_definition=s_row[3] or {},
                total_rows=s_row[4],
                total_columns=s_row[5],
                captured_at=s_row[6],
            )

            cur.execute(
                """
                SELECT rule_id, rule_name, dimension, rule_type, parameters,
                       null_policy, weight, severity, is_advisory, is_required,
                       gate_enabled, score_enabled, acceptance_threshold,
                       conflict_group, is_primary_scoring_rule
                FROM quality_rules WHERE tenant_id = %s AND ruleset_id = %s;
                """,
                (tenant_id, ruleset_id),
            )
            r_rows = cur.fetchall()
            rules = [
                QualityRule(
                    rule_id=r[0],
                    rule_code=r[1],
                    dimension=r[2],
                    rule_type=r[3],
                    parameters=r[4] or {},
                    null_policy=r[5].lower(),
                    contribution_weight=float(r[6]),
                    is_critical=(r[7] == "CRITICAL"),
                    is_advisory=r[8],
                    is_required=r[9],
                    gate_enabled=r[10],
                    score_enabled=r[11],
                    acceptance_threshold=r[12],
                    conflict_group=r[13],
                    is_primary_scoring_rule=r[14],
                    ruleset_id=ruleset_id,
                )
                for r in r_rows
            ]

            cur.execute(
                """
                SELECT dimension_weights, publication_threshold, gate_rules
                FROM scoring_policies WHERE tenant_id = %s AND policy_id = %s;
                """,
                (tenant_id, policy_id),
            )
            p_row = cur.fetchone()
            assert p_row is not None, f"Policy {policy_id} not found"
            policy = scoring_policy_from_row(
                policy_id=policy_id,
                dimension_weights=p_row[0],
                publication_threshold=p_row[1],
                gate_rules=p_row[2],
            )

            outlier_cols = (
                outlier_config.get("outlier_columns", [])
                if isinstance(outlier_config, dict)
                else []
            )

            return RunSpec(
                run_id=run_id,
                tenant_id=tenant_id,
                snapshot=snapshot,
                rules=rules,
                policy=policy,
                execution_profile=execution_profile,
                outlier_columns=outlier_cols,
                ruleset_id=ruleset_id,
                policy_id=policy_id,
            )
