"""Editor-only privacy scan queue and bounded summaries; never return pinned definitions."""
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import get_current_user, get_db_connection
from dq_scoring.presentation.api.pagination import Pagination, pagination
from dq_scoring.services.privacy_scan_service import (
    CreatePrivacyScan,
    create_scan,
    get_scan,
)

router = APIRouter(prefix="/api/v1", tags=["Privacy scans"])
EDITOR_ROLES = frozenset({"WORKSPACE_ADMIN", "DATA_OWNER", "DATA_STEWARD"})


def _editor(user: AuthenticatedUser) -> None:
    if user.role not in EDITOR_ROLES:
        raise HTTPException(403, "FORBIDDEN")


@router.post("/snapshots/{snapshot_id}/privacy-scans", status_code=202)
def queue_scan(snapshot_id: UUID, payload: CreatePrivacyScan, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    _editor(user)
    return create_scan(conn, user, snapshot_id, payload)


@router.get("/privacy-scans/{scan_id}")
def read_scan(scan_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    _editor(user)
    return get_scan(conn, user.tenant_id, scan_id)


@router.get("/privacy-scans/{scan_id}/findings")
def read_scan_findings(scan_id: UUID, paging: Pagination = Depends(pagination), user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    _editor(user)
    scan = get_scan(conn, user.tenant_id, scan_id)
    items = (scan["result_summary"] or {}).get("findings", [])
    if paging.q:
        items = [item for item in items if paging.q.casefold() in item.get("column_name", "").casefold()]
    start = (paging.page - 1) * paging.page_size
    return {"items": items[start:start + paging.page_size], "total": len(items), "page": paging.page, "page_size": paging.page_size}
