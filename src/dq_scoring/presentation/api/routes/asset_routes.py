"""Data Asset and Dataset Snapshot routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from dq_scoring.adapters.llm.gateway_settings import (
    LlmSettings,
    get_llm_settings,
    get_local_llm_settings,
)
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    ai_http_error,
    check_tenant_access,
    get_current_user,
    get_db_connection,
    get_pg_dsn,
    require_active_role,
)
from dq_scoring.presentation.api.pagination import (
    Page,
    Pagination,
    contains,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.asset_schemas import (
    AiRecommendationRequest,
    AssetResponse,
    CreateAssetRequest,
    SemanticConfirmRequest,
    SemanticInferRequest,
    SnapshotResponse,
)
from dq_scoring.services.ai_recommendation_service import recommend_with_ai
from dq_scoring.services.privacy_policy import (
    mask_preview_and_profile,
    resolve_snapshot_protection,
)
from dq_scoring.services.semantic_service import (
    SemanticError,
    apply_confirmations,
    confirmed_labels,
    infer_semantics,
    semantic_view,
)
from dq_scoring.services.snapshot_profile_service import (
    SnapshotProfileError,
    current_full_profile,
    ensure_full_profile,
    load_snapshot,
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


def _profile(conn, user, snapshot_id, mode):
    require_active_role(conn, user)
    try:
        snapshot = load_snapshot(conn,user.tenant_id,snapshot_id)
        protection = resolve_snapshot_protection(conn,user.tenant_id,snapshot_id)
        if mode == "SAMPLE":
            row = conn.execute("SELECT manifest FROM dataset_snapshots WHERE tenant_id=%s AND snapshot_id=%s",(user.tenant_id,snapshot_id)).fetchone()
            _, result = mask_preview_and_profile(None,(row[0] or {}).get("profile",{}),protection.protected_columns)
            result = {**result,"mode":"SAMPLE","profiler_version":"import-prefix-v1","sampling_method":"PREFIX",
                "scanned_rows":result.get("sample_rows",0),"generated_at":snapshot.captured_at,"is_sample":True}
            return {"state":"COMPLETE","current":True,"stale":False,"result":result}
        job = current_full_profile(conn,user.tenant_id,snapshot_id)
        current = job is not None
        if job is None:
            from psycopg.rows import dict_row

            from dq_scoring.services.snapshot_profile_service import PROFILE_COLUMNS
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT {PROFILE_COLUMNS} FROM snapshot_profile_jobs WHERE tenant_id=%s AND snapshot_id=%s ORDER BY created_at DESC,profile_id DESC LIMIT 1",(user.tenant_id,snapshot_id))
                job = cur.fetchone()
            if job is None:
                return {"state":None,"current":False,"stale":False,"result":None}
        _, result = mask_preview_and_profile(None,job["result"],protection.protected_columns)
        return {k:v for k,v in {**job,"result":result,"current":current,"stale":not current}.items() if k not in ("tenant_id",)}
    except SnapshotProfileError as error:
        raise HTTPException(404 if error.code=="RESOURCE_NOT_FOUND" else 409,detail=error.code) from None


@router.get("/snapshots/{snapshot_id}/profile")
def snapshot_profile(snapshot_id: UUID, mode: Literal["SAMPLE","FULL"]="SAMPLE",
    user: AuthenticatedUser=Depends(get_current_user), conn: psycopg.Connection=Depends(get_db_connection)):
    return _profile(conn,user,snapshot_id,mode)


@router.post("/snapshots/{snapshot_id}/profiles/full",status_code=202)
def submit_full_profile(snapshot_id: UUID,user: AuthenticatedUser=Depends(get_current_user),conn: psycopg.Connection=Depends(get_db_connection)):
    require_active_role(conn,user,frozenset({"DATA_ENGINEER","DATA_OWNER","DATA_STEWARD","WORKSPACE_ADMIN"}))
    try:
        job=ensure_full_profile(conn,user.tenant_id,snapshot_id,user.user_id,requeue_failed=True)
    except SnapshotProfileError as error:
        raise HTTPException(404 if error.code=="RESOURCE_NOT_FOUND" else 409,detail=error.code) from None
    return {k:job[k] for k in ("profile_id","snapshot_id","state","fingerprint","profiler_version")}


def _heuristic(conn, user, snapshot_id, domain, selected, profile_mode="SAMPLE"):
    from dq_scoring.services.rule_recommendations import recommend_rules
    data = _preview(conn, user, snapshot_id)
    selected_profile = _profile(conn,user,snapshot_id,profile_mode)
    if selected_profile.get("state") != "COMPLETE" or not selected_profile.get("current"):
        raise HTTPException(409,detail="FULL_PROFILE_REQUIRED")
    data = {**data,"profile":selected_profile["result"]}
    templates = []
    with conn.cursor() as cur:
        cur.execute("SELECT template_id,template_code,domain,rules_payload FROM ruleset_templates WHERE (tenant_id IS NULL OR tenant_id=%s) AND status='ACTIVE' ORDER BY template_code", (user.tenant_id,))
        templates.extend({"template_id": str(r[0]), "template_code": r[1], "domain": r[2], "rules_payload": r[3]} for r in cur.fetchall())
        cur.execute("SELECT template_id,template_code,domain FROM scoring_policy_templates WHERE tenant_id IS NULL OR tenant_id=%s ORDER BY template_code", (user.tenant_id,))
        templates.extend({"template_id": str(r[0]), "template_code": r[1], "domain": r[2]} for r in cur.fetchall())
    return data, recommend_rules(data["schema_definition"], data["profile"], domain, selected, templates, confirmed_labels(conn, user.tenant_id, snapshot_id)[1])


@router.get("/snapshots/{snapshot_id}/recommendations")
def snapshot_recommendations(snapshot_id: UUID, domain: Literal["FINANCE", "RETAIL", "HEALTHCARE", "TRANSPORTATION", "GENERAL"] = "GENERAL", priorities: str = "COMPLETENESS,VALIDITY,UNIQUENESS", profile_mode: Literal["SAMPLE","FULL"]="SAMPLE", user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    from dq_scoring.core.models import StandardDimension
    selected = tuple(value.strip() for value in priorities.split(",") if value.strip())
    if set(selected) - {d.value for d in StandardDimension}:
        raise HTTPException(422, detail="INVALID_PRIORITIES")
    return _heuristic(conn, user, snapshot_id, domain, selected, profile_mode)[1]


@router.get("/ai/status")
def ai_status(user: AuthenticatedUser = Depends(get_current_user), settings: LlmSettings = Depends(get_llm_settings)) -> dict:
    on = settings.enabled and settings.configured
    return {"enabled": on, "model": settings.model if on else None, "recommendations": on, "narrative": on}


@router.post("/snapshots/{snapshot_id}/recommendations/ai")
async def snapshot_ai_recommendations(
    snapshot_id: UUID, body: AiRecommendationRequest,
    user: AuthenticatedUser = Depends(get_current_user), dsn: str = Depends(get_pg_dsn),
    settings: LlmSettings = Depends(get_llm_settings),
) -> dict:
    """Explicit inference; holds no DB connection across the gateway call (see recommend_with_ai)."""
    priorities = tuple(dict.fromkeys(body.priorities))
    return await recommend_with_ai(
        dsn, user, snapshot_id, body.engine, priorities, settings,
        lambda conn: _heuristic(conn, user, snapshot_id, body.domain, priorities, body.profile_mode),
    )


def _semantic_data(conn, user, snapshot_id, profile_mode):
    """Masked schema + selected profile; FULL must be current and COMPLETE."""
    selected = _profile(conn, user, snapshot_id, profile_mode)
    if selected.get("state") != "COMPLETE" or not selected.get("current"):
        raise HTTPException(409, detail="FULL_PROFILE_REQUIRED")
    snapshot = load_snapshot(conn, user.tenant_id, snapshot_id)
    return {"schema_definition": snapshot.schema_definition, "profile": selected["result"], "total_rows": snapshot.total_rows}


@router.get("/snapshots/{snapshot_id}/semantics")
def snapshot_semantics(snapshot_id: UUID, profile_mode: Literal["SAMPLE", "FULL"] = "SAMPLE",
    user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    """Local evidence and confirmed projection; never calls a model."""
    require_active_role(conn, user)
    return semantic_view(conn, user, snapshot_id, _semantic_data(conn, user, snapshot_id, profile_mode))


@router.put("/snapshots/{snapshot_id}/semantics")
def confirm_snapshot_semantics(snapshot_id: UUID, body: SemanticConfirmRequest,
    user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    try:
        return apply_confirmations(conn, user, snapshot_id, body.expected_revision, body.reason, [(c.column, c.label) for c in body.changes])
    except SnapshotProfileError as error:
        raise HTTPException(404 if error.code == "RESOURCE_NOT_FOUND" else 409, detail=error.code) from None
    except SemanticError as error:
        raise ai_http_error(error.code) from None


@router.post("/snapshots/{snapshot_id}/semantics/infer")
async def infer_snapshot_semantics(
    snapshot_id: UUID, body: SemanticInferRequest,
    user: AuthenticatedUser = Depends(get_current_user), dsn: str = Depends(get_pg_dsn),
    api_settings: LlmSettings = Depends(get_llm_settings), local_settings: LlmSettings = Depends(get_local_llm_settings),
) -> dict:
    """Explicit inference for the chosen provider only; candidates are never persisted or confirmed."""
    return await infer_semantics(
        dsn, user, snapshot_id, body.provider, local_settings if body.provider == "LOCAL" else api_settings,
        lambda conn: _semantic_data(conn, user, snapshot_id, body.profile_mode),
    )
