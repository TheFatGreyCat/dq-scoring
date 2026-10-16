"""Scoring Policy configuration and independent approval routes (AC-003)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.policy_mapping import scoring_policy_from_row
from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.presentation.api import governance
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    get_current_user,
    get_db_connection,
)
from dq_scoring.presentation.api.pagination import (
    Page,
    Pagination,
    contains,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.policy_schemas import (
    ApprovePolicyRequest,
    CreatePolicyRequest,
    PolicyResponse,
    SubmitPolicyRequest,
)

router = APIRouter(prefix="/api/v1/policies", tags=["Scoring Policies & Approval Workflow"])


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(
    req: CreatePolicyRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> PolicyResponse:
    """Create a new Scoring Policy in DRAFT status."""
    policy_id = uuid4()
    now = datetime.now(UTC)
    version_str = f"1.0.0-{policy_id.hex[:6]}"

    policy_hash = compute_deterministic_hash(req.model_dump(mode="json"))
    gate_rules_data = {
        "gate_fail_threshold": req.gate_fail_threshold,
        "gate_warn_threshold": req.gate_warn_threshold,
        "critical_acceptance_threshold": req.critical_acceptance_threshold,
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scoring_policies (
                policy_id, tenant_id, name, version, config_hash, status,
                created_by, created_at, dimension_weights,
                publication_threshold, gate_rules
            ) VALUES (%s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s);
            """,
            (
                policy_id,
                current_user.tenant_id,
                req.name,
                version_str,
                policy_hash,
                current_user.user_id,
                now,
                Jsonb(req.dimension_weights),
                req.min_coverage_threshold,
                Jsonb(gate_rules_data),
            ),
        )

    return PolicyResponse(
        policy_id=policy_id,
        tenant_id=current_user.tenant_id,
        name=req.name,
        status="DRAFT",
        current_version=1,
        gate_fail_threshold=req.gate_fail_threshold,
        gate_warn_threshold=req.gate_warn_threshold,
        min_coverage_threshold=req.min_coverage_threshold,
        critical_acceptance_threshold=req.critical_acceptance_threshold,
        created_by=current_user.user_id,
        created_at=now,
        dimension_weights=req.dimension_weights,
    )



def _policy_response(cur: psycopg.Cursor, policy_id: UUID) -> PolicyResponse:
    """Build the response from what is stored, never from request echoes or defaults."""
    cur.execute(
        """
        SELECT policy_id, tenant_id, COALESCE(name, version), status, created_by, created_at,
               dimension_weights, publication_threshold, gate_rules
        FROM scoring_policies WHERE policy_id = %s;
        """,
        (policy_id,),
    )
    row = cur.fetchone()
    policy = scoring_policy_from_row(policy_id=row[0], dimension_weights=row[6], publication_threshold=row[7], gate_rules=row[8])
    return PolicyResponse(
        policy_id=row[0],
        tenant_id=row[1],
        name=row[2],
        status=row[3],
        current_version=1,
        gate_fail_threshold=policy.gate_fail_threshold,
        gate_warn_threshold=policy.gate_warn_threshold,
        min_coverage_threshold=policy.publication_threshold,
        critical_acceptance_threshold=policy.critical_acceptance_threshold,
        created_by=row[4],
        created_at=row[5],
        dimension_weights=row[6] or {},
    )


@router.get("", response_model=Page[PolicyResponse])
def list_policies(status: Literal["DRAFT", "PENDING_APPROVAL", "ACTIVE", "DEPRECATED"] | None = None, paging: Pagination = Depends(pagination), user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)) -> dict:
    predicates, params = ["tenant_id=%s"], [user.tenant_id]
    if paging.q:
        predicates.append("COALESCE(name,version) ILIKE %s")
        params.append(contains(paging.q))
    if status:
        predicates.append("status=%s")
        params.append(status)
    result = fetch_page(conn, projection="policy_id", source="scoring_policies", predicates=predicates, params=params, order="created_at DESC,policy_id DESC", paging=paging)
    with conn.cursor() as cur:
        result["items"] = [_policy_response(cur, row["policy_id"]) for row in result["items"]]
    return result


@router.get("/{policy_id}", response_model=PolicyResponse)
def get_policy(policy_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)) -> PolicyResponse:
    with conn.cursor() as cur:
        cur.execute("SELECT policy_id FROM scoring_policies WHERE tenant_id=%s AND policy_id=%s", (user.tenant_id, policy_id))
        if not cur.fetchone():
            raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
        return _policy_response(cur, policy_id)


@router.post("/{policy_id}/submit", response_model=PolicyResponse)
def submit_policy(
    policy_id: UUID,
    req: SubmitPolicyRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> PolicyResponse:
    """Submit a DRAFT policy revision for independent approval (DRAFT -> PENDING_APPROVAL)."""
    with conn.cursor() as cur:
        governance.submit_for_approval(cur, governance.POLICIES, policy_id, current_user)
        return _policy_response(cur, policy_id)


@router.post("/{policy_id}/approve", response_model=PolicyResponse)
def approve_policy(
    policy_id: UUID,
    req: ApprovePolicyRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> PolicyResponse:
    """AC-003: Approve a PENDING_APPROVAL policy; it supersedes the tenant's ACTIVE policy."""
    with conn.cursor() as cur:
        governance.approve(cur, governance.POLICIES, policy_id, current_user)
        return _policy_response(cur, policy_id)
