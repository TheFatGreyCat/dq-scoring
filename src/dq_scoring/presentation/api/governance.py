"""Shared approval workflow for rulesets and scoring policies (AC-003, FR-GOV-006).

DRAFT --submit--> PENDING_APPROVAL --approve (independent approver)--> ACTIVE
Approving supersedes the previously ACTIVE revision in the same scope (DEPRECATED).
Every transition re-checks the expected status in its UPDATE, so concurrent requests
cannot both succeed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from fastapi import HTTPException, status
from psycopg import sql

from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import check_tenant_access

APPROVER_ROLES = frozenset({"DATA_OWNER", "DATA_STEWARD", "WORKSPACE_ADMIN"})


@dataclass(frozen=True)
class GovernedTable:
    table: str
    id_column: str
    label: str
    supersede_scope: tuple[str, ...]
    """Columns that define 'the one ACTIVE revision' (matches the partial unique indexes)."""


RULESETS = GovernedTable("rulesets", "ruleset_id", "Ruleset", ("tenant_id", "asset_id"))
POLICIES = GovernedTable("scoring_policies", "policy_id", "Scoring Policy", ("tenant_id",))
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


def approve(cur: psycopg.Cursor, t: GovernedTable, entity_id: UUID, user: AuthenticatedUser) -> None:
    record = _load_for_update(cur, t, entity_id, user)
    current = record["status"]
    if current == "ACTIVE":
        raise _bad_request(f"{t.label} is already ACTIVE.")
    if current == "DRAFT":
        raise _bad_request(f"{t.label} must be submitted for approval before it can be approved.")
    if current != "PENDING_APPROVAL":
        raise _bad_request(f"Cannot approve {t.label.lower()} in {current} status.")
    if user.user_id in (record["created_by"], record["submitted_by"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Independent approval violation: Creator/submitter cannot approve their own {t.label.lower()}.",
        )
    if user.role not in APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: Approver must have DATA_OWNER, DATA_STEWARD, or WORKSPACE_ADMIN role.",
        )

    cur.execute(
        sql.SQL("UPDATE {table} SET status = 'DEPRECATED' WHERE status = 'ACTIVE' AND {scope};").format(
            table=sql.Identifier(t.table),
            scope=sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in t.supersede_scope),
        ),
        tuple(record[c] for c in t.supersede_scope),
    )
    _transition(
        cur,
        t,
        entity_id,
        "PENDING_APPROVAL",
        sql.SQL("status = 'ACTIVE', approved_by = %s, approved_at = %s"),
        (user.user_id, datetime.now(UTC)),
    )
