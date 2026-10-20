"""Per-run execution view: request state vs run-scoped Spark observations."""

from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends

from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import get_current_user, get_db_connection
from dq_scoring.presentation.api.routes.run_routes import (
    ADMIN_ROLE,
    RunScope,
    _authorize_run,
)
from dq_scoring.services.run_execution_service import (
    RunExecutionResponse,
    run_execution,
)

router = APIRouter(prefix="/api/v1/runs", tags=["Evaluation Runs"])


@router.get("/{run_id}/execution", response_model=RunExecutionResponse)
def get_run_execution(
    run_id: UUID,
    scope: RunScope | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> RunExecutionResponse:
    """Same parent authorization as status/events; Spark/cluster identifiers are workspace-admin only."""
    with conn.cursor() as cur:
        scope = _authorize_run(cur, run_id, user, scope)
        return run_execution(cur, user.tenant_id, run_id, show_cluster_ids=user.role == ADMIN_ROLE and scope == "workspace")
