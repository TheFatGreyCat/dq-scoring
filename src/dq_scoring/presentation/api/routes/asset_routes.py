"""Data Asset and Dataset Snapshot routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    check_tenant_access,
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
from dq_scoring.presentation.api.schemas.asset_schemas import (
    AssetResponse,
    CreateAssetRequest,
    SnapshotResponse,
)
from dq_scoring.services.privacy_policy import (
    mask_preview_and_profile,
    resolve_snapshot_protection,
)

router = APIRouter(prefix="/api/v1", tags=["Data Assets & Snapshots"])


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(
    req: CreateAssetRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> AssetResponse:
    """Register a new logical Data Asset for the authenticated tenant."""
    asset_id = uuid4()
    now = datetime.now(UTC)
    slug = req.name.lower().replace(" ", "-")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_assets (
                asset_id, tenant_id, asset_name, slug, format,
                owner_user_id, created_by, created_at
            )
            VALUES (%s, %s, %s, %s, 'CSV', %s, %s, %s)
            RETURNING asset_id, tenant_id, asset_name, created_at;
            """,
            (asset_id, current_user.tenant_id, req.name, f"{slug}-{asset_id.hex[:6]}", current_user.user_id, current_user.user_id, now),
        )
        row = cur.fetchone()
        return AssetResponse(
            asset_id=row[0],
            tenant_id=row[1],
            name=row[2],
            created_at=row[3],
        )


@router.get("/assets", response_model=Page[AssetResponse])
def list_assets(
    format: Literal["CSV", "PARQUET", "JSONL"] | None = None,
    paging: Pagination = Depends(pagination),
    user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    predicates, params = ["tenant_id=%s"], [user.tenant_id]
    if paging.q:
        predicates.append("(asset_name ILIKE %s OR slug ILIKE %s)")
        params.extend([contains(paging.q)] * 2)
    if format:
        predicates.append("format=%s")
        params.append(format)
    return fetch_page(conn, projection="asset_id,tenant_id,asset_name AS name,format,slug,current_snapshot_id,version_count,created_at", source="data_assets", predicates=predicates, params=params, order="created_at DESC,asset_id DESC", paging=paging)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id,tenant_id,asset_name AS name,format,slug,current_snapshot_id,version_count,created_at FROM data_assets WHERE tenant_id=%s AND asset_id=%s", (user.tenant_id, asset_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
        return dict(zip([col.name for col in cur.description], row, strict=True))


@router.get("/snapshots", response_model=Page[SnapshotResponse])
def list_snapshots(
    asset_id: UUID | None = None,
    format: Literal["CSV", "PARQUET", "JSONL"] | None = None,
    version_status: Literal["ACTIVE", "SUPERSEDED", "ARCHIVED"] | None = None,
    paging: Pagination = Depends(pagination),
    user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    predicates, params = ["tenant_id=%s"], [user.tenant_id]
    for column, value in (("asset_id", asset_id), ("source_descriptor->>'format'", format), ("version_status", version_status)):
        if value is not None:
            predicates.append(f"{column}=%s")
            params.append(value)
    return fetch_page(conn, projection="snapshot_id,tenant_id,asset_id,source_kind,source_descriptor,schema_definition,total_rows,total_columns,captured_at,version_number,version_status", source="dataset_snapshots", predicates=predicates, params=params, order="captured_at DESC,snapshot_id DESC", paging=paging)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
def get_snapshot(
    snapshot_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> SnapshotResponse:
    """Retrieve snapshot details with strict tenant isolation."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_id, tenant_id, asset_id, source_kind, source_descriptor,
                   schema_definition, total_rows, total_columns, captured_at
            FROM dataset_snapshots
            WHERE snapshot_id = %s;
            """,
            (snapshot_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset Snapshot not found.",
            )
        check_tenant_access(row[1], current_user.tenant_id)
        return SnapshotResponse(
            snapshot_id=row[0],
            tenant_id=row[1],
            asset_id=row[2],
            source_kind=row[3],
            source_descriptor=row[4],
            schema_definition=row[5],
            total_rows=row[6],
            total_columns=row[7],
            captured_at=row[8],
        )


def _preview(conn, user, snapshot_id):
    from dq_scoring.presentation.api.routes.import_routes import _check_import_role
    _check_import_role(user)
    with conn.cursor() as cur:
        cur.execute("SELECT schema_definition,manifest,source_descriptor,total_rows,total_columns FROM dataset_snapshots WHERE tenant_id=%s AND snapshot_id=%s", (user.tenant_id, snapshot_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
        manifest = row[1] or {}
        if "preview" not in manifest:
            raise HTTPException(404, detail="PREVIEW_UNAVAILABLE")
        protected = resolve_snapshot_protection(conn, user.tenant_id, snapshot_id).protected_columns
        preview, profile = mask_preview_and_profile(manifest["preview"], manifest.get("profile", {}), protected)
        return {"schema_definition": row[0], "preview": preview, "profile": profile, "warnings": manifest.get("warnings", []), "source_descriptor": row[2], "total_rows": row[3], "total_columns": row[4]}


@router.get("/snapshots/{snapshot_id}/preview")
def snapshot_preview(snapshot_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    return _preview(conn, user, snapshot_id)


@router.get("/snapshots/{snapshot_id}/recommendations")
def snapshot_recommendations(snapshot_id: UUID, domain: Literal["FINANCE", "RETAIL", "HEALTHCARE", "TRANSPORTATION", "GENERAL"] = "GENERAL", priorities: str = "COMPLETENESS,VALIDITY,UNIQUENESS", user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    from dq_scoring.core.models import StandardDimension
    from dq_scoring.services.rule_recommendations import recommend_rules
    selected = tuple(value.strip() for value in priorities.split(",") if value.strip())
    if set(selected) - {d.value for d in StandardDimension}:
        raise HTTPException(422, detail="INVALID_PRIORITIES")
    data = _preview(conn, user, snapshot_id)
    templates = []
    with conn.cursor() as cur:
        cur.execute("SELECT template_id,template_code,domain,rules_payload FROM ruleset_templates WHERE (tenant_id IS NULL OR tenant_id=%s) AND status='ACTIVE' ORDER BY template_code", (user.tenant_id,))
        templates.extend({"template_id": str(r[0]), "template_code": r[1], "domain": r[2], "rules_payload": r[3]} for r in cur.fetchall())
        cur.execute("SELECT template_id,template_code,domain FROM scoring_policy_templates WHERE tenant_id IS NULL OR tenant_id=%s ORDER BY template_code", (user.tenant_id,))
        templates.extend({"template_id": str(r[0]), "template_code": r[1], "domain": r[2]} for r in cur.fetchall())
    return recommend_rules(data["schema_definition"], data["profile"], domain, selected, templates)
