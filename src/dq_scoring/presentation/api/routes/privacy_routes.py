"""API routes for sensitive data findings and asset protection policies."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from dq_scoring.adapters.storage.s3_settings import (
    S3Settings,
    get_import_settings,
    get_s3_settings,
)
from dq_scoring.common.protected_transport import protected_connect
from dq_scoring.ports.object_store import IObjectStorePort
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    get_current_user,
    get_db_connection,
    get_pg_dsn,
    validate_api_session,
)
from dq_scoring.presentation.api.pagination import Pagination, pagination
from dq_scoring.presentation.api.routes.import_routes import (
    ALLOWED_IMPORT_ROLES,
    _get_storage_adapter,
)
from dq_scoring.presentation.api.schemas.privacy_schemas import (
    ColumnClassificationsResponse,
    FindingResponse,
    PolicyResponse,
    SensitiveFindingsResponse,
    UpdateClassificationsRequest,
    UpdateFindingStatusRequest,
    UpdatePolicyRequest,
)
from dq_scoring.services.column_classification_service import (
    get_classifications,
    update_classifications,
)
from dq_scoring.services.privacy_service import PrivacyService, begin_tenant_transaction

EXPORT_CHUNK_BYTES = 1024 * 1024
router = APIRouter(prefix="/api/v1", tags=["Sensitive Data & Privacy"])
POLICY_WRITE_ROLES = frozenset({"WORKSPACE_ADMIN", "DATA_OWNER", "DATA_STEWARD"})


def _require_import_role(user: AuthenticatedUser) -> None:
    if user.role not in ALLOWED_IMPORT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Role does not have permission to access sensitive findings or policies",
        )


def _require_policy_write_role(user: AuthenticatedUser) -> None:
    if user.role not in POLICY_WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Role does not have permission to modify protection policies or finding statuses",
        )


@router.get("/snapshots/{snapshot_id}/sensitive-findings", response_model=SensitiveFindingsResponse)
def get_snapshot_sensitive_findings(
    snapshot_id: UUID,
    paging: Pagination = Depends(pagination),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> SensitiveFindingsResponse:
    _require_import_role(current_user)
    return PrivacyService.get_sensitive_findings(conn, current_user.tenant_id, snapshot_id, paging)


@router.get("/snapshots/{snapshot_id}/column-classifications", response_model=ColumnClassificationsResponse)
def get_snapshot_column_classifications(
    snapshot_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> ColumnClassificationsResponse:
    _require_import_role(current_user)
    return get_classifications(conn, current_user.tenant_id, snapshot_id)


@router.put("/assets/{asset_id}/column-classifications", response_model=ColumnClassificationsResponse)
def update_asset_column_classifications(
    asset_id: UUID,
    payload: UpdateClassificationsRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> ColumnClassificationsResponse:
    _require_policy_write_role(current_user)
    return update_classifications(conn, current_user, asset_id, payload)


@router.patch("/sensitive-findings/{finding_id}", response_model=FindingResponse)
def update_sensitive_finding_status(
    finding_id: UUID,
    payload: UpdateFindingStatusRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> FindingResponse:
    _require_policy_write_role(current_user)
    return PrivacyService.update_finding_status(
        conn,
        current_user.user_id,
        current_user.tenant_id,
        finding_id,
        payload.expected_status,
        payload.status,
        payload.reason,
    )


@router.get("/assets/{asset_id}/protection-policy", response_model=PolicyResponse)
def get_asset_protection_policy(
    asset_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> PolicyResponse:
    _require_import_role(current_user)
    return PrivacyService.get_asset_protection_policy(conn, current_user.tenant_id, asset_id)


@router.put("/assets/{asset_id}/protection-policy", response_model=PolicyResponse)
def update_asset_protection_policy(
    asset_id: UUID,
    payload: UpdatePolicyRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> PolicyResponse:
    _require_policy_write_role(current_user)
    return PrivacyService.update_asset_protection_policy(
        conn,
        current_user.user_id,
        current_user.tenant_id,
        asset_id,
        payload.expected_version,
        payload.categories,
    )


MASKED_EXPORT_ROLES = ALLOWED_IMPORT_ROLES | {"BUSINESS_VIEWER"}


def _require_export_role(user: AuthenticatedUser) -> None:
    if user.role not in MASKED_EXPORT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Role does not have permission to export masked dataset",
        )


def _stream_and_cleanup(path: Path, workdir: Path):
    try:
        with path.open("rb") as handle:
            yield from iter(lambda: handle.read(EXPORT_CHUNK_BYTES), b"")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@router.api_route("/assets/{asset_id}/masked-export", methods=["GET", "POST"])
def export_asset_masked_parquet(
    asset_id: UUID,
    snapshot_id: UUID | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    dsn: str = Depends(get_pg_dsn),
    store: IObjectStorePort = Depends(_get_storage_adapter),
    s3_settings: S3Settings = Depends(get_s3_settings),
) -> StreamingResponse:
    _require_export_role(current_user)
    scratch = Path(get_import_settings().temp_root)
    scratch.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="dq-export-", dir=scratch))
    try:
        # Own connection: the export commits before object I/O, which the request-scoped transaction forbids.
        with protected_connect(dsn, autocommit=False) as conn:
            validate_api_session(conn)
            begin_tenant_transaction(conn, current_user.tenant_id)
            artifact = PrivacyService.export_masked_parquet(
                conn, store, s3_settings, current_user.tenant_id, asset_id, snapshot_id, workdir
            )
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return StreamingResponse(
        _stream_and_cleanup(artifact.path, workdir),
        media_type="application/vnd.apache.parquet",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Content-Length": str(artifact.path.stat().st_size),
            "Cache-Control": "no-store",
        },
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )
