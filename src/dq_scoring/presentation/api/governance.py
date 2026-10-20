"""Shared approval workflow for rulesets and scoring policies (AC-003, FR-GOV-006).

DRAFT --submit--> PENDING_APPROVAL --approve--> ACTIVE
Approving supersedes the previously ACTIVE revision in the same scope (DEPRECATED).
Every transition re-checks the expected status in its UPDATE, so concurrent requests
cannot both succeed; approvals additionally serialize per tenant (advisory lock) so the
supersede step and the audit hash chain never race.

Approval needs an independent approver. The only exception is an explicit self-approval by a
WORKSPACE_ADMIN of a ruleset or scoring policy they created/submitted: it needs a non-blank
reason and is recorded in audit_logs inside the same transaction. Templates never get it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException, status
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import StringConstraints

from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import check_tenant_access

APPROVER_ROLES = frozenset({"DATA_OWNER", "DATA_STEWARD", "WORKSPACE_ADMIN"})
SELF_APPROVER_ROLE = "WORKSPACE_ADMIN"
MAX_SELF_APPROVAL_REASON = 500
SelfApprovalReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SELF_APPROVAL_REASON)]


@dataclass(frozen=True)
class GovernedTable:
    table: str
    id_column: str
    label: str
    supersede_scope: tuple[str, ...]
    """Columns that define 'the one ACTIVE revision' (matches the partial unique indexes)."""
    audit_resource_type: str | None = None
    """Set only for kinds whose approval is audited and may be self-approved by a workspace admin."""


RULESETS = GovernedTable("rulesets", "ruleset_id", "Ruleset", ("tenant_id", "asset_id"), "RULESET")
POLICIES = GovernedTable("scoring_policies", "policy_id", "Scoring Policy", ("tenant_id",), "SCORING_POLICY")
TEMPLATES = GovernedTable("ruleset_templates", "template_id", "Ruleset Template", ("tenant_id", "template_code"))


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _load_for_update(
    cur: psycopg.Cursor, t: GovernedTable, entity_id: UUID, user: AuthenticatedUser
) -> dict[str, Any]:
    columns = ["tenant_id", "status", "created_by", "submitted_by", *t.supersede_scope]
    cur.execute(
        sql.SQL("SELECT {cols} FROM {table} WHERE {id} = %s FOR UPDATE;").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, dict.fromkeys(columns))),
            table=sql.Identifier(t.table),
            id=sql.Identifier(t.id_column),
        ),
        (entity_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{t.label} not found.")
    record = dict(zip(dict.fromkeys(columns), row, strict=True))
    check_tenant_access(record["tenant_id"], user.tenant_id)
    return record


def _transition(cur: psycopg.Cursor, t: GovernedTable, entity_id: UUID, expected: str, assignments: sql.Composable, params: tuple) -> None:
    cur.execute(
        sql.SQL("UPDATE {table} SET {assign} WHERE {id} = %s AND status = %s;").format(
            table=sql.Identifier(t.table), assign=assignments, id=sql.Identifier(t.id_column)
        ),
        (*params, entity_id, expected),
    )
    if cur.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{t.label} changed while this request was processed. Reload and try again.",
        )


def submit_for_approval(cur: psycopg.Cursor, t: GovernedTable, entity_id: UUID, user: AuthenticatedUser) -> None:
    record = _load_for_update(cur, t, entity_id, user)
    if record["status"] != "DRAFT":
        raise _bad_request(
            f"Only DRAFT {t.label.lower()} revisions can be submitted for approval (current status: {record['status']})."
        )
    _transition(
        cur,
        t,
        entity_id,
        "DRAFT",
        sql.SQL("status = 'PENDING_APPROVAL', submitted_by = %s, submitted_at = %s"),
        (user.user_id, datetime.now(UTC)),
    )


def approve(
    cur: psycopg.Cursor,
    t: GovernedTable,
    entity_id: UUID,
    user: AuthenticatedUser,
    self_approval_reason: str | None = None,
) -> None:
    user = _current_member(cur, user, lock=True)
    # Serialize approvals per tenant before reading state: concurrent approvals in one supersede
    # scope would otherwise both miss the other's ACTIVE row and trip the unique index.
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));", (f"governance-approve:{user.tenant_id}",))
    record = _load_for_update(cur, t, entity_id, user)
    current = record["status"]
    if current == "ACTIVE":
        raise _bad_request(f"{t.label} is already ACTIVE.")
    if current == "DRAFT":
        raise _bad_request(f"{t.label} must be submitted for approval before it can be approved.")
    if current != "PENDING_APPROVAL":
        raise _bad_request(f"Cannot approve {t.label.lower()} in {current} status.")
    is_own = user.user_id in (record["created_by"], record["submitted_by"])
    may_self_approve = is_own and can_self_approve(t, record, user, cur)
    if is_own and not may_self_approve:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Independent approval violation: Creator/submitter cannot approve their own {t.label.lower()}.",
        )
    if user.role not in APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: Approver must have DATA_OWNER, DATA_STEWARD, or WORKSPACE_ADMIN role.",
        )
    reason = (self_approval_reason or "").strip() if may_self_approve else None
    if may_self_approve and not reason:
        raise HTTPException(
            status_code=422,
            detail=f"Self-approval of your own {t.label.lower()} requires an explicit non-blank reason.",
        )

    now = datetime.now(UTC)
    cur.execute(
        sql.SQL("UPDATE {table} SET status = 'DEPRECATED' WHERE status = 'ACTIVE' AND {scope} RETURNING {id};").format(
            table=sql.Identifier(t.table),
            id=sql.Identifier(t.id_column),
            scope=sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in t.supersede_scope),
        ),
        tuple(record[c] for c in t.supersede_scope),
    )
    superseded = [str(row[0]) for row in cur.fetchall()]
    _transition(
        cur,
        t,
        entity_id,
        "PENDING_APPROVAL",
        sql.SQL("status = 'ACTIVE', approved_by = %s, approved_at = %s"),
        (user.user_id, now),
    )
    if t.audit_resource_type is not None:
        _audit_approval(cur, t, entity_id, user, record, now, reason, superseded)


def _current_member(cur: psycopg.Cursor, user: AuthenticatedUser, *, lock: bool = False) -> AuthenticatedUser:
    cur.execute(
        "SELECT role FROM tenant_memberships WHERE tenant_id=%s AND user_id=%s AND status='ACTIVE'"
        + (" FOR SHARE" if lock else ""),
        (user.tenant_id, user.user_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Active workspace membership required.")
    return user.model_copy(update={"role": row[0]})


def can_self_approve(t: GovernedTable, record: dict[str, Any], user: AuthenticatedUser, cur: psycopg.Cursor) -> bool:
    """Whether `user` may explicitly self-approve this PENDING_APPROVAL revision (server decides; UI only mirrors)."""
    user = _current_member(cur, user)
    return (
        t.audit_resource_type is not None
        and user.role == SELF_APPROVER_ROLE
        and record["status"] == "PENDING_APPROVAL"
        and user.user_id in (record["created_by"], record["submitted_by"])
    )


def _audit_approval(
    cur: psycopg.Cursor,
    t: GovernedTable,
    entity_id: UUID,
    user: AuthenticatedUser,
    record: dict[str, Any],
    now: datetime,
    reason: str | None,
    superseded: list[str],
) -> None:
    """Append the approval to the tenant's hash-chained audit log in the caller's transaction."""
    cur.execute(
        sql.SQL("SELECT version, config_hash FROM {table} WHERE {id} = %s;").format(
            table=sql.Identifier(t.table), id=sql.Identifier(t.id_column)
        ),
        (entity_id,),
    )
    version, config_hash = cur.fetchone()
    cur.execute(
        "SELECT entry_hash FROM audit_logs WHERE tenant_id = %s ORDER BY event_timestamp DESC, audit_id DESC LIMIT 1;",
        (user.tenant_id,),
    )
    previous = cur.fetchone()
    diff = {
        "self_approval": reason is not None,
        "reason": reason,
        "revision": {"version": version, "config_hash": config_hash},
        "created_by": str(record["created_by"]),
        "submitted_by": str(record["submitted_by"]),
        "before": {"status": "PENDING_APPROVAL", "approved_by": None},
        "after": {"status": "ACTIVE", "approved_by": str(user.user_id), "approved_at": now.isoformat()},
        "superseded_ids": superseded,
    }
    prev_hash = previous[0] if previous else "GENESIS"
    audit_id = uuid4()
    entry_hash = compute_deterministic_hash(
        {
            "audit_id": str(audit_id),
            "prev": prev_hash,
            "tenant_id": str(user.tenant_id),
            "actor": str(user.user_id),
            "action": "APPROVE",
            "resource_type": t.audit_resource_type,
            "resource_id": str(entity_id),
            "at": now.isoformat(),
            "diff": diff,
        }
    )
    cur.execute(
        """
        INSERT INTO audit_logs (audit_id, tenant_id, actor_user_id, action, resource_type, resource_id,
                                diff_json, prev_log_hash, entry_hash, event_timestamp)
        VALUES (%s, %s, %s, 'APPROVE', %s, %s, %s, %s, %s, %s);
        """,
        (audit_id, user.tenant_id, user.user_id, t.audit_resource_type, entity_id, Jsonb(diff), prev_hash, entry_hash, now),
    )
