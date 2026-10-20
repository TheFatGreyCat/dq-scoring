"""Evaluation run submission and status polling routes."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from dq_scoring.adapters.db.policy_mapping import scoring_policy_from_row
from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RunSpec
from dq_scoring.ports.queue_port import IQueuePort
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    check_tenant_access,
    get_current_user,
    get_db_connection,
    get_queue_port,
)
from dq_scoring.presentation.api.pagination import (
    Page,
    Pagination,
    date_bounds,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.run_schemas import (
    RunEventPage,
    RunResponse,
    RunStatusResponse,
    TriggerRunRequest,
)

router = APIRouter(prefix="/api/v1/runs", tags=["Evaluation Runs"])

RunScope = Literal["mine", "workspace"]
ADMIN_ROLE = "WORKSPACE_ADMIN"


def effective_scope(user: AuthenticatedUser, scope: RunScope | None) -> RunScope:
    """Owner-only for everyone; tenant-wide visibility is a WORKSPACE_ADMIN privilege (BR-020)."""
    is_admin = user.role == ADMIN_ROLE
    if scope == "workspace" and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Workspace scope requires a workspace administrator.")
    return scope or ("workspace" if is_admin else "mine")


def _encode_cursor(run_id: UUID, created_at: datetime, event_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{run_id}|{created_at.isoformat()}|{event_id}".encode()).decode()


def _decode_cursor(cursor: str, run_id: UUID) -> tuple[datetime, UUID]:
    """A continuation is only valid for the run that issued it."""
    try:
        cursor_run, stamp, event_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        created_at = datetime.fromisoformat(stamp)
        if created_at.tzinfo is None or UUID(cursor_run) != run_id:
            raise ValueError
        return created_at, UUID(event_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="INVALID_CURSOR") from exc


@router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_run(
    req: TriggerRunRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    queue: IQueuePort = Depends(get_queue_port),
) -> RunResponse:
    """Trigger an asynchronous DQ evaluation run."""
    with conn.cursor() as cur:
        # 1. Fetch Snapshot
        cur.execute(
            """
            SELECT snapshot_id, tenant_id, asset_id, source_kind, source_descriptor,
                   schema_definition, total_rows, total_columns, captured_at
            FROM dataset_snapshots WHERE snapshot_id = %s;
            """,
            (req.snapshot_id,),
        )
        snap_row = cur.fetchone()
        if not snap_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset Snapshot not found.")
        check_tenant_access(snap_row[1], current_user.tenant_id)

        snapshot = DatasetSnapshot(
            snapshot_id=snap_row[0],
            tenant_id=snap_row[1],
            asset_id=snap_row[2],
            source_kind=snap_row[3],
            source_descriptor=snap_row[4],
            schema_definition=snap_row[5],
            total_rows=snap_row[6],
            total_columns=snap_row[7],
            captured_at=snap_row[8],
        )

        # 2. Fetch Ruleset & Rules
        cur.execute(
            "SELECT tenant_id, status, asset_id FROM rulesets WHERE ruleset_id = %s;",
            (req.ruleset_id,),
        )
        ruleset_row = cur.fetchone()
        if not ruleset_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ruleset not found.")
        check_tenant_access(ruleset_row[0], current_user.tenant_id)
        if ruleset_row[1] != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="CONFIGURATION_NOT_APPROVED: Ruleset must be in ACTIVE status before evaluation.",
            )
        if ruleset_row[2] != snapshot.asset_id:
            raise HTTPException(422, detail="ASSET_CONFIGURATION_MISMATCH")

        cur.execute(
            """
            SELECT rule_id, rule_name, dimension, rule_type, parameters, null_policy,
                   is_required, severity, gate_enabled, score_enabled, weight,
                   acceptance_threshold, is_advisory
            FROM quality_rules WHERE ruleset_id = %s;
            """,
            (req.ruleset_id,),
        )
        rule_rows = cur.fetchall()
        rules = [
            QualityRule(
                rule_id=r[0],
                rule_code=r[1],
                dimension=r[2],
                rule_type=r[3],
                parameters=r[4],
                null_policy=r[5].lower(),
                is_required=r[6],
                is_critical=(r[7] == "CRITICAL"),
                gate_enabled=r[8],
                score_enabled=r[9],
                contribution_weight=float(r[10]),
                acceptance_threshold=r[11],
                is_advisory=r[12],
            )
            for r in rule_rows
        ]
        columns = {c["name"] if isinstance(c, dict) else c for c in snapshot.schema_definition.get("columns", [])}
        referenced = {value for rule in rules for key, value in rule.parameters.items() if key in ("column", "target_column", "left_column", "right_column") and isinstance(value, str)}
        if not rules or (referenced | set(req.outlier_columns)) - columns:
            raise HTTPException(422, detail="INCOMPATIBLE_CONFIGURATION")

        # 3. Fetch Scoring Policy
        cur.execute(
            """
            SELECT tenant_id, publication_threshold, gate_rules, status, dimension_weights
            FROM scoring_policies WHERE policy_id = %s;
            """,
            (req.policy_id,),
        )
        pol_row = cur.fetchone()
        if not pol_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scoring Policy not found.")
        check_tenant_access(pol_row[0], current_user.tenant_id)
        if pol_row[3] != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="CONFIGURATION_NOT_APPROVED: Scoring Policy must be in ACTIVE status before evaluation.",
            )

        policy = scoring_policy_from_row(
            policy_id=req.policy_id,
            dimension_weights=pol_row[4],
            publication_threshold=pol_row[1],
            gate_rules=pol_row[2],
        )

        run_id = uuid4()
        now = datetime.now(UTC)
        spec = RunSpec(
            run_id=run_id,
            tenant_id=current_user.tenant_id,
            snapshot=snapshot,
            rules=rules,
            policy=policy,
            execution_profile=req.execution_profile,
            outlier_columns=req.outlier_columns,
            ruleset_id=req.ruleset_id,
            policy_id=req.policy_id,
            created_by=current_user.user_id,
        )

        idem_key = req.idempotency_key or f"run-{run_id}"
        actual_run_id = queue.enqueue_run(spec, idempotency_key=idem_key)

        return RunResponse(
            run_id=actual_run_id,
            tenant_id=current_user.tenant_id,
            snapshot_id=req.snapshot_id,
            ruleset_id=req.ruleset_id,
            policy_id=req.policy_id,
            status="QUEUED",
            created_at=now,
            owned_by_me=True,
        )

@router.get("", response_model=Page[RunResponse])
def list_runs(
    asset_id: UUID | None = None, snapshot_id: UUID | None = None,
    status: Literal["QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"] | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    scope: RunScope | None = None, created_by: UUID | None = None,
    paging: Pagination = Depends(pagination), user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    date_bounds(created_from, created_to)
    scope = effective_scope(user, scope)
    if created_by is not None and (user.role != ADMIN_ROLE or scope != "workspace"):
        raise HTTPException(403, detail="Creator filter requires workspace scope as a workspace administrator.")
    predicates, params = ["r.tenant_id=%s"], [user.tenant_id]
    if scope == "mine":
        created_by = user.user_id
    for column, value in (("s.asset_id", asset_id), ("r.snapshot_id", snapshot_id), ("r.run_status", status), ("r.created_by", created_by)):
        if value is not None:
            predicates.append(f"{column}=%s")
            params.append(value)
    if created_from:
        predicates.append("r.created_at >= %s")
        params.append(created_from)
    if created_to:
        predicates.append("r.created_at < %s")
        params.append(created_to)
    page = fetch_page(conn, projection="r.run_id,r.tenant_id,r.snapshot_id,r.ruleset_id,r.policy_id,r.run_status AS status,r.created_at,r.completed_at,r.execution_error AS error_message,a.assessment_id,r.created_by", source="evaluation_runs r JOIN dataset_snapshots s ON s.tenant_id=r.tenant_id AND s.snapshot_id=r.snapshot_id LEFT JOIN assessments a ON a.tenant_id=r.tenant_id AND a.run_id=r.run_id", predicates=predicates, params=params, order="r.created_at DESC,r.run_id DESC", paging=paging)
    for item in page["items"]:
        owner = item.pop("created_by")
        item["owned_by_me"] = owner == user.user_id
        item["created_by"] = owner if scope == "workspace" else None
    return page


def _authorize_run(cur: psycopg.Cursor, run_id: UUID, user: AuthenticatedUser, scope: RunScope | None) -> RunScope:
    """Parent authorization shared by status and events; foreign or unowned runs are indistinguishable from missing."""
    scope = effective_scope(user, scope)
    cur.execute("SELECT tenant_id, created_by FROM evaluation_runs WHERE run_id = %s;", (run_id,))
    row = cur.fetchone()
    if not row or row[0] != user.tenant_id or (scope == "mine" and row[1] != user.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation Run not found.")
    return scope


@router.get("/{run_id}/status", response_model=RunStatusResponse)
def get_run_status(
    run_id: UUID,
    scope: RunScope | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> RunStatusResponse:
    """AC-012 & IF-UI-005: Poll execution run status and link to assessment if finished."""
    with conn.cursor() as cur:
        scope = _authorize_run(cur, run_id, current_user, scope)
        cur.execute(
            """
            SELECT r.run_status, r.execution_error, r.tenant_id, a.assessment_id,
                   COALESCE(r.completed_at,r.heartbeat_at,r.started_at,r.created_at),
                   r.created_at,r.started_at,r.completed_at,r.heartbeat_at,r.attempt_count,r.created_by
            FROM evaluation_runs r
            LEFT JOIN assessments a ON a.tenant_id = r.tenant_id AND a.run_id = r.run_id
            WHERE r.run_id = %s AND r.tenant_id = %s;
            """,
            (run_id, current_user.tenant_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation Run not found.")
        return RunStatusResponse(
            run_id=run_id,
            status=row[0],
            error_message=row[1],
            assessment_id=row[3],
            updated_at=row[4],
            created_at=row[5], started_at=row[6], completed_at=row[7],
            heartbeat_at=row[8], attempt_count=row[9],
            created_by=row[10] if scope == "workspace" else None,
            owned_by_me=row[10] == current_user.user_id,
        )


@router.get("/{run_id}/events", response_model=RunEventPage)
def list_run_events(
    run_id: UUID,
    scope: RunScope | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> RunEventPage:
    """Bounded, allowlisted timeline; event_payload never leaves the database."""
    after = _decode_cursor(cursor, run_id) if cursor else None
    with conn.cursor() as cur:
        _authorize_run(cur, run_id, current_user, scope)
        cur.execute(
            """
            SELECT event_id, event_type, attempt_count, lease_generation, created_at, left(event_payload->>'error', 200)
            FROM run_events
            WHERE tenant_id = %s AND run_id = %s AND event_type <> 'SPARK_OBSERVED' AND (%s::timestamptz IS NULL OR (created_at, event_id) > (%s::timestamptz, %s::uuid))
            ORDER BY created_at, event_id
            LIMIT %s;
            """,
            (current_user.tenant_id, run_id, after and after[0], after and after[0], after and after[1], limit + 1),
        )
        rows = cur.fetchall()
    page = rows[:limit]
    return RunEventPage(
        items=[
            {"event_id": r[0], "event_type": r[1], "attempt_count": r[2], "lease_generation": r[3], "created_at": r[4], "error_code": r[5]}
            for r in page
        ],
        next_cursor=_encode_cursor(run_id, page[-1][4], page[-1][0]) if len(rows) > limit else None,
    )
