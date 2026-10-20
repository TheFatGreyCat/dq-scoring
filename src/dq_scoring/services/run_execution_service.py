"""Run execution projection: request state and per-attempt Spark observations, kept separate.

Observations are read from run_events (SPARK_OBSERVED) written by the leased worker; they are
bound to a lease generation, bounded, validated and labelled fresh/stale/ended/unknown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import psycopg
from pydantic import BaseModel, Field, ValidationError

from dq_scoring.workers.monitoring import OBSERVATION_KEEPALIVE_SECONDS

MAX_ATTEMPTS = 10
MAX_JOBS = 20
FRESH_AFTER_SECONDS = 2 * OBSERVATION_KEEPALIVE_SECONDS
TERMINAL_EVENTS = ("RUN_SUCCEEDED", "RUN_FAILED", "RUN_CANCELLED")
ACTIVE_STATUSES = ("LEASED", "RUNNING")


class SparkJob(BaseModel):
    job_id: int = Field(ge=0)
    status: Literal["RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN"] = "UNKNOWN"
    stages: int = Field(ge=0, le=100000)
    tasks: int = Field(ge=0)
    active_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)


class SparkObservationPayload(BaseModel):
    application_id: str = Field(max_length=128, pattern=r"^[A-Za-z0-9_.\-]+$")
    group_id: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9_.\-]+$")
    jobs: list[SparkJob] = Field(max_length=MAX_JOBS)


class SparkAttempt(BaseModel):
    state: Literal["OBSERVED", "STALE", "ENDED", "UNKNOWN"] = "UNKNOWN"
    observed_at: datetime | None = None
    application_id: str | None = None
    group_id: str | None = None
    jobs: list[SparkJob] = Field(default_factory=list)


class ExecutionAttempt(BaseModel):
    lease_generation: int
    attempt_count: int
    claimed_at: datetime | None = None
    outcome: str | None = None
    spark: SparkAttempt


class ExecutionRequest(BaseModel):
    status: str
    attempt_count: int
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    completed_at: datetime | None = None


class RunExecutionResponse(BaseModel):
    request: ExecutionRequest
    attempts: list[ExecutionAttempt]
    observed_scope: Literal["RUN_ATTEMPT"] = "RUN_ATTEMPT"


def _spark_view(row: tuple | None, current: bool, run_active: bool, ended: bool, show_cluster_ids: bool) -> SparkAttempt:
    if row is None:
        return SparkAttempt()
    payload, observed_at = row
    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        payload = {**payload, "jobs": payload["jobs"][:MAX_JOBS]}
    try:
        parsed = SparkObservationPayload.model_validate(payload)
    except ValidationError:
        return SparkAttempt()
    if ended or not current or not run_active:
        state = "ENDED"
    elif (datetime.now(UTC) - observed_at).total_seconds() > FRESH_AFTER_SECONDS:
        state = "STALE"
    else:
        state = "OBSERVED"
    return SparkAttempt(
        state=state,
        observed_at=observed_at,
        application_id=parsed.application_id if show_cluster_ids else None,
        group_id=parsed.group_id if show_cluster_ids else None,
        jobs=parsed.jobs,
    )


def run_execution(cur: psycopg.Cursor, tenant_id: UUID, run_id: UUID, *, show_cluster_ids: bool) -> RunExecutionResponse:
    """Caller must already have authorized the parent run for this user and scope."""
    cur.execute(
        "SELECT run_status, attempt_count, lease_generation, started_at, heartbeat_at, completed_at "
        "FROM evaluation_runs WHERE tenant_id=%s AND run_id=%s;",
        (tenant_id, run_id),
    )
    status, attempt_count, current_generation, started_at, heartbeat_at, completed_at = cur.fetchone()
    cur.execute(
        "SELECT lease_generation, max(attempt_count), "
        "min(created_at) FILTER (WHERE event_type='RUN_CLAIMED'), "
        "(array_agg(event_type ORDER BY created_at DESC) FILTER (WHERE event_type = ANY(%s)))[1] "
        "FROM run_events WHERE tenant_id=%s AND run_id=%s AND lease_generation > 0 "
        "GROUP BY lease_generation ORDER BY lease_generation DESC LIMIT %s;",
        (list(TERMINAL_EVENTS), tenant_id, run_id, MAX_ATTEMPTS),
    )
    attempts = cur.fetchall()
    cur.execute(
        "SELECT DISTINCT ON (lease_generation) lease_generation, event_payload, created_at "
        "FROM run_events WHERE tenant_id=%s AND run_id=%s AND event_type='SPARK_OBSERVED' AND lease_generation = ANY(%s) "
        "ORDER BY lease_generation, created_at DESC;",
        (tenant_id, run_id, [a[0] for a in attempts]),
    )
    observations = {generation: (payload, created) for generation, payload, created in cur.fetchall()}
    return RunExecutionResponse(
        request=ExecutionRequest(
            status=status, attempt_count=attempt_count, started_at=started_at,
            heartbeat_at=heartbeat_at, completed_at=completed_at,
        ),
        attempts=[
            ExecutionAttempt(
                lease_generation=generation, attempt_count=count, claimed_at=claimed, outcome=outcome,
                spark=_spark_view(
                    observations.get(generation), generation == current_generation,
                    status in ACTIVE_STATUSES, outcome is not None, show_cluster_ids,
                ),
            )
            for generation, count, claimed, outcome in attempts
        ],
    )
