"""API endpoints for MinIO dataset imports, uploads, and storage browsing."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from dq_scoring.adapters.db.postgres_import_store import PostgresImportStore
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import (
    ImportSettings,
    S3Settings,
    get_import_settings,
    get_s3_settings,
)
from dq_scoring.ports.object_store import IObjectStorePort, ObjectRef, UploadedPart
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import get_current_user, get_db_connection
from dq_scoring.presentation.api.errors import create_problem_response
from dq_scoring.presentation.api.pagination import (
    Page,
    Pagination,
    contains,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.asset_schemas import SnapshotResponse
from dq_scoring.presentation.api.schemas.import_schemas import (
    CompleteImportRequest,
    ConfigureImportRequest,
    CreateImportRequest,
    ImportSessionResponse,
    ImportSessionSummary,
    RegisterImportRequest,
    StorageObjectItem,
    StorageObjectsResponse,
)
from dq_scoring.services.dataset_import_service import (
    DatasetImportService,
    ImportRegistrationError,
)
from dq_scoring.services.privacy_policy import (
    mask_preview_and_profile,
    session_protected_columns,
)

router = APIRouter(prefix="/api/v1", tags=["Dataset Storage & Imports"])
ALLOWED_IMPORT_ROLES = frozenset({"WORKSPACE_ADMIN", "DATA_OWNER", "DATA_STEWARD", "DATA_ENGINEER"})
logger = logging.getLogger(__name__)


def _check_import_role(user: AuthenticatedUser) -> None:
    if user.role not in ALLOWED_IMPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Role does not have permission to manage imports or preview data",
        )


def _get_storage_adapter(settings: S3Settings = Depends(get_s3_settings)) -> IObjectStorePort:
    return S3ObjectStoreAdapter(settings=settings)


def _build_session_response(
    row: dict[str, Any],
    import_settings: ImportSettings,
    conn: psycopg.Connection,
    user: AuthenticatedUser,
) -> ImportSessionResponse:
    size = int(row.get("size_bytes") or 0)
    part_size = import_settings.part_bytes
    part_count = max(1, math.ceil(size / part_size)) if size > 0 else 1
    manifest = row.get("manifest") or {}
    parts_map = manifest.get("parts") or {}
    completed_parts = sorted([int(k) for k in parts_map]) if parts_map else []
    preview, profile = manifest.get("preview"), manifest.get("profile")
    if preview is not None or profile is not None:
        preview, profile = mask_preview_and_profile(
            preview, profile, session_protected_columns(conn, user.tenant_id, row)
        )
    return ImportSessionResponse(
        upload_id=row["upload_id"],
        status=row["status"],
        format=row["format"],
        part_size=part_size,
        part_count=part_count,
        size_bytes=size,
        original_filename=row["original_filename"],
        asset_id=row.get("asset_id"),
        asset_name=row.get("asset_name"),
        client_request_id=row.get("client_request_id"),
        error_code=manifest.get("error_code") or (
            "IMPORT_EXPIRED"
            if row.get("expires_at") and row["expires_at"] < datetime.now(row["expires_at"].tzinfo) and row.get("status") not in ("REGISTERED", "FAILED", "ABORTED")
            else (row.get("error_reason") if row.get("status") in ("FAILED", "REJECTED") else None)
        ),
        invalid_params=manifest.get("invalid_params"),
        warnings=manifest.get("warnings"),
        preview=preview,
        profile=profile,
        snapshot_id=row.get("registered_snapshot_id"),
        completed_parts=completed_parts,
        completed_part_details=[{"part_number": part, "etag": parts_map[str(part)]["etag"]} for part in completed_parts],
        schema_definition={"columns": manifest.get("columns", [])},
        source_descriptor=manifest.get("source_descriptor", {}),
        total_rows=manifest.get("exact_row_count"),
        total_columns=len(manifest.get("columns", [])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
        csv_options=manifest.get("csv_options"),
    )


@router.get("/storage/objects", response_model=StorageObjectsResponse)
def list_storage_objects(
    prefix: str = Query(default=""),
    continuation_token: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    scope: str = Query(default="tenant"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    store: IObjectStorePort = Depends(_get_storage_adapter),
    s3_settings: S3Settings = Depends(get_s3_settings),
) -> StorageObjectsResponse:
    """List objects in staging storage. Tenants are confined to their imports prefix unless WORKSPACE_ADMIN."""
    _check_import_role(current_user)
    if scope not in ("tenant", "staging"):
        raise HTTPException(status_code=422, detail="Invalid storage scope")
    if scope == "staging" and current_user.role != "WORKSPACE_ADMIN":
        raise HTTPException(status_code=403, detail="Global staging access requires a workspace administrator")

    tenant_prefix = f"imports/{current_user.tenant_id}/"
    if current_user.role == "WORKSPACE_ADMIN" and scope == "staging":
        search_prefix = prefix
    else:
        if prefix and not prefix.startswith(tenant_prefix):
            search_prefix = f"{tenant_prefix}{prefix.lstrip('/')}"
        else:
            search_prefix = prefix or tenant_prefix

    try:
        items, next_token = store.list_objects(
            bucket=s3_settings.bucket_staging,
            prefix=search_prefix,
            continuation_token=continuation_token,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable or bucket not found",
        ) from exc

    return StorageObjectsResponse(
        items=[
            StorageObjectItem(
                bucket=m.ref.bucket,
                key=m.ref.key,
                size_bytes=m.size_bytes,
                last_modified=m.last_modified,
            )
            for m in items
        ],
        next_token=next_token,
    )


@router.get("/imports", response_model=Page[ImportSessionSummary])
def list_import_sessions(
    status: Literal["INITIATED", "UPLOADING", "STAGED", "VERIFYING", "VERIFIED", "REJECTED", "FAILED", "ABORTED", "REGISTERED"] | None = None,
    paging: Pagination = Depends(pagination),
    user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    settings: ImportSettings = Depends(get_import_settings),
):
    _check_import_role(user)
    predicates, params = ["tenant_id=%s"], [user.tenant_id]
    if status:
        predicates.append("status=%s")
        params.append(status)
    if paging.q:
        predicates.append("(original_filename ILIKE %s OR asset_name ILIKE %s)")
        params.extend([contains(paging.q), contains(paging.q)])
    page = fetch_page(conn, projection="upload_id,status,asset_id,asset_name,format,original_filename,size_bytes,manifest,error_reason,registered_snapshot_id,created_at,updated_at,expires_at",
        source="dataset_upload_sessions", predicates=predicates, params=params,
        order="created_at DESC,upload_id DESC", paging=paging)
    page["items"] = [ImportSessionSummary.model_validate(_build_session_response(row, settings, conn, user).model_dump()) for row in page["items"]]
    return page


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def create_import_session(
    req: CreateImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    store: IObjectStorePort = Depends(_get_storage_adapter),
    s3_settings: S3Settings = Depends(get_s3_settings),
    import_settings: ImportSettings = Depends(get_import_settings),
) -> JSONResponse:
    """Create a new dataset upload or staging import session."""
    _check_import_role(current_user)
    from dq_scoring.services.privacy_rule_service import ensure_initialized

    ensure_initialized(conn, current_user.tenant_id)
    request_fingerprint = hashlib.sha256(json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    # 1. Check idempotency by client_request_id
    existing = PostgresImportStore.get_by_client_request(
        conn,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        client_request_id=req.client_request_id,
    )
    if existing:
        # Check payload equality
        same_target = (
            str(existing.get("asset_id")) == str(req.asset_id)
            if req.asset_id
            else existing.get("asset_name") == req.asset_name
        )
        if same_target and (existing.get("manifest") or {}).get("request_fingerprint") == request_fingerprint:
            resp_model = _build_session_response(existing, import_settings, conn, current_user)
            return JSONResponse(status_code=status.HTTP_201_CREATED, content=resp_model.model_dump(mode="json"))
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Import session with this client_request_id already exists with different parameters.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    # 2. Check asset existence if asset_id provided
    if req.asset_id is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asset_id FROM data_assets WHERE tenant_id = %s AND asset_id = %s;",
                (current_user.tenant_id, req.asset_id),
            )
            if not cur.fetchone():
                return create_problem_response(
                    status_code=status.HTTP_404_NOT_FOUND,
                    title="Not Found",
                    detail=f"Target Data Asset {req.asset_id} not found in tenant.",
                    extensions={"error_code": "RESOURCE_NOT_FOUND"},
                )

    # 3. Check file size limits
    if req.size_bytes > import_settings.max_bytes:
        return create_problem_response(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            title="Payload Too Large",
            detail=f"File size {req.size_bytes} bytes exceeds maximum allowed limit {import_settings.max_bytes} bytes.",
            extensions={"error_code": "SIZE_LIMIT_EXCEEDED"},
        )

    upload_id = uuid4()
    ext = req.format.lower()
    staging_key = f"imports/{current_user.tenant_id}/{upload_id}/source.{ext}"

    manifest: dict[str, Any] = {
        "request_fingerprint": request_fingerprint,
        "client_request_id": str(req.client_request_id),
        "original_filename": req.original_filename,
        "format": req.format,
        "csv_options": req.csv_options.model_dump() if req.csv_options else None,
        "staging_bucket": s3_settings.bucket_staging,
        "staging_key": staging_key,
        "parts": {},
    }

    if req.source:
        if req.source.bucket != s3_settings.bucket_staging or (
            current_user.role != "WORKSPACE_ADMIN" and not req.source.key.startswith(f"imports/{current_user.tenant_id}/")
        ):
            return create_problem_response(status_code=404, title="Not Found", detail="Source object not found in this workspace.", extensions={"error_code": "RESOURCE_NOT_FOUND"})
        # Existing object in staging
        source_ref = ObjectRef(bucket=req.source.bucket, key=req.source.key)
        try:
            meta = store.head(source_ref)
        except FileNotFoundError:
            return create_problem_response(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Not Found",
                detail=f"Source object s3://{req.source.bucket}/{req.source.key} not found.",
                extensions={"error_code": "RESOURCE_NOT_FOUND"},
            )
        except (BotoCoreError, ClientError, OSError):
            return create_problem_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                title="Storage Unavailable",
                detail="Unable to verify source storage object.",
                extensions={"error_code": "STORAGE_UNAVAILABLE"},
            )
        if meta.size_bytes != req.size_bytes or meta.size_bytes > import_settings.max_bytes:
            return create_problem_response(status_code=409, title="Object changed", detail="Source size differs from the selected object.", extensions={"error_code": "OBJECT_CHANGED"})

        manifest["source_ref"] = {"bucket": req.source.bucket, "key": req.source.key, "etag": meta.etag, "version_id": meta.version_id, "size_bytes": meta.size_bytes}
        row = PostgresImportStore.create_session(
            conn,
            upload_id=upload_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            asset_id=req.asset_id,
            asset_name=req.asset_name,
            client_request_id=req.client_request_id,
            format=req.format,
            original_filename=req.original_filename,
            size_bytes=meta.size_bytes,
            staging_key=req.source.key,
            destination_location=source_ref.s3a_uri,
            multipart_id=None,
            status="STAGED",
            manifest=manifest,
        )
    else:
        # Multipart upload initiated
        try:
            mp_id = store.create_multipart(s3_settings.bucket_staging, staging_key)
        except (BotoCoreError, ClientError, OSError):
            return create_problem_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                title="Storage Unavailable",
                detail="Unable to initialize multipart upload in object store.",
                extensions={"error_code": "STORAGE_UNAVAILABLE"},
            )

        row = PostgresImportStore.create_session(
            conn,
            upload_id=upload_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            asset_id=req.asset_id,
            asset_name=req.asset_name,
            client_request_id=req.client_request_id,
            format=req.format,
            original_filename=req.original_filename,
            size_bytes=req.size_bytes,
            staging_key=staging_key,
            destination_location=None,
            multipart_id=mp_id,
            status="INITIATED",
            manifest=manifest,
        )

    resp_model = _build_session_response(row, import_settings, conn, current_user)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=resp_model.model_dump(mode="json"))


@router.post("/imports/{upload_id}/parts/{part_number}")
async def upload_part(
    upload_id: UUID,
    part_number: int,
    request: Request,
    content_length: int = Header(..., alias="Content-Length"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    store: IObjectStorePort = Depends(_get_storage_adapter),
    s3_settings: S3Settings = Depends(get_s3_settings),
    import_settings: ImportSettings = Depends(get_import_settings),
) -> JSONResponse:
    """Stream a single multipart chunk to temporary spool and upload to S3."""
    _check_import_role(current_user)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (PostgresImportStore._hash_advisory_lock(upload_id, part_number),))

    session = PostgresImportStore.get_by_id(conn, upload_id=upload_id, tenant_id=current_user.tenant_id)
    if not session:
        return create_problem_response(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Import session {upload_id} not found.",
            extensions={"error_code": "RESOURCE_NOT_FOUND"},
        )

    if session.get("expires_at") and session["expires_at"] < datetime.now(session["expires_at"].tzinfo):
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Import session has expired.",
            extensions={"error_code": "IMPORT_EXPIRED"},
        )

    if session["status"] not in ("INITIATED", "UPLOADING"):
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail=f"Cannot upload parts to session in status '{session['status']}'.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    mp_id = session.get("multipart_id")
    if not mp_id:
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Session has no active multipart upload ID.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    part_count = max(1, math.ceil(session["size_bytes"] / import_settings.part_bytes))
    if part_number < 1 or part_number > part_count:
        return create_problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid Argument",
            detail=f"Part number {part_number} out of valid range (1..{part_count}).",
            extensions={"error_code": "INVALID_PART_NUMBER"},
        )

    # Check part size limit
    if content_length > import_settings.part_bytes:
        return create_problem_response(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            title="Payload Too Large",
            detail=f"Part size {content_length} exceeds part limit {import_settings.part_bytes}.",
            extensions={"error_code": "SIZE_LIMIT_EXCEEDED"},
        )
    expected_length = min(import_settings.part_bytes, session["size_bytes"] - (part_number - 1) * import_settings.part_bytes)
    if content_length != expected_length:
        return create_problem_response(
            status_code=422, title="Invalid part length",
            detail="Part length must match the declared dataset size.",
            extensions={"error_code": "CONTENT_LENGTH_MISMATCH"},
        )

    # Spool part to bounded temporary file and calculate SHA256
    temp_dir = Path(import_settings.temp_root) / f"upload-{upload_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path_str = tempfile.mkstemp(dir=temp_dir, prefix=f"part-{part_number}-")
    temp_path = Path(temp_path_str)

    hasher = hashlib.sha256()
    received_bytes = 0

    try:
        with await run_in_threadpool(open, temp_fd, "wb") as f:
            async for chunk in request.stream():
                received_bytes += len(chunk)
                if received_bytes > content_length:
                    return create_problem_response(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        title="Bad Request",
                        detail="Streamed bytes exceeded declared Content-Length.",
                        extensions={"error_code": "CONTENT_LENGTH_MISMATCH"},
                    )
                hasher.update(chunk)
                await run_in_threadpool(f.write, chunk)

        if received_bytes != content_length:
            return create_problem_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Bad Request",
                detail=f"Received bytes ({received_bytes}) did not match declared Content-Length ({content_length}).",
                extensions={"error_code": "CONTENT_LENGTH_MISMATCH"},
            )

        part_sha256 = hasher.hexdigest()

        # Check existing recorded part
        manifest = session.get("manifest") or {}
        parts_manifest = manifest.get("parts") or {}
        existing_part = parts_manifest.get(str(part_number))

        if existing_part:
            if existing_part.get("sha256") == part_sha256:
                # Replay with same digest -> return existing ETag
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "upload_id": str(upload_id),
                        "part_number": part_number,
                        "etag": existing_part["etag"],
                        "sha256": part_sha256,
                    },
                )
            else:
                return create_problem_response(
                    status_code=status.HTTP_409_CONFLICT,
                    title="Conflict",
                    detail=f"Conflicting payload for part {part_number} with different checksum.",
                    extensions={"error_code": "PART_CHECKSUM_MISMATCH"},
                )

        # Upload part to S3
        staging_key = session["staging_key"]
        with await run_in_threadpool(temp_path.open, "rb") as stream:
            etag = await run_in_threadpool(
                store.upload_part,
                bucket=s3_settings.bucket_staging,
                key=staging_key,
                multipart_id=mp_id,
                part_number=part_number,
                stream=stream,
                length=received_bytes,
            )

        PostgresImportStore.record_part(
            conn,
            upload_id=upload_id,
            part_number=part_number,
            etag=etag,
            sha256=part_sha256,
            size_bytes=received_bytes,
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "upload_id": str(upload_id),
                "part_number": part_number,
                "etag": etag,
                "sha256": part_sha256,
            },
        )
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.warning("Import part scratch cleanup failed for upload %s", upload_id)


@router.post("/imports/{upload_id}/complete")
def complete_import(
    upload_id: UUID,
    req: CompleteImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    store: IObjectStorePort = Depends(_get_storage_adapter),
    s3_settings: S3Settings = Depends(get_s3_settings),
    import_settings: ImportSettings = Depends(get_import_settings),
) -> JSONResponse:
    """Complete an active multipart upload and transition session to STAGED."""
    _check_import_role(current_user)
    with conn.cursor() as cur:
        cur.execute("SELECT upload_id FROM dataset_upload_sessions WHERE upload_id = %s AND tenant_id = %s FOR UPDATE", (upload_id, current_user.tenant_id))

    session = PostgresImportStore.get_by_id(conn, upload_id=upload_id, tenant_id=current_user.tenant_id)
    if not session:
        return create_problem_response(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Import session {upload_id} not found.",
            extensions={"error_code": "RESOURCE_NOT_FOUND"},
        )

    if session.get("expires_at") and session["expires_at"] < datetime.now(session["expires_at"].tzinfo):
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Import session has expired.",
            extensions={"error_code": "IMPORT_EXPIRED"},
        )
    if session["status"] == "STAGED":
        # Idempotent response
        resp_model = _build_session_response(session, import_settings, conn, current_user)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=resp_model.model_dump(mode="json"))

    if session["status"] not in ("INITIATED", "UPLOADING"):
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail=f"Cannot complete import in status '{session['status']}'.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    mp_id = session.get("multipart_id")
    if not mp_id:
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Session has no active multipart upload ID.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    # Convert parts to UploadedPart port objects
    parts = [UploadedPart(part_number=p.part_number, etag=p.etag) for p in req.parts]
    recorded = (session.get("manifest") or {}).get("parts", {})
    expected_numbers = set(range(1, math.ceil(session["size_bytes"] / import_settings.part_bytes) + 1))
    supplied = {p.part_number: p.etag.strip('"') for p in req.parts}
    if (
        len(supplied) != len(req.parts)
        or set(supplied) != expected_numbers
        or set(recorded) != {str(n) for n in expected_numbers}
        or sum(p.get("size_bytes", 0) for p in recorded.values()) != session["size_bytes"]
        or any(recorded.get(str(n), {}).get("etag", "").strip('"') != etag for n, etag in supplied.items())
    ):
        return create_problem_response(status_code=409, title="Incomplete upload", detail="Complete all recorded upload parts before finalizing.", extensions={"error_code": "IMPORT_STATE_CONFLICT"})

    try:
        meta = store.complete_multipart(
            bucket=s3_settings.bucket_staging,
            key=session["staging_key"],
            multipart_id=mp_id,
            parts=parts,
        )
    except (BotoCoreError, ClientError, OSError):
        # Crash recovery: if complete_multipart already succeeded, HEAD staging object to reconcile
        try:
            meta = store.head(ObjectRef(bucket=s3_settings.bucket_staging, key=session["staging_key"]))
            if meta.size_bytes != session["size_bytes"]:
                return create_problem_response(
                    status_code=status.HTTP_409_CONFLICT,
                    title="Conflict",
                    detail="Staged object size does not match session declared size.",
                    extensions={"error_code": "OBJECT_CHANGED"},
                )
        except (BotoCoreError, ClientError, OSError):
            return create_problem_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                title="Storage Error",
                detail="Unable to complete multipart upload in object storage.",
                extensions={"error_code": "STORAGE_UNAVAILABLE"},
            )
    if meta.size_bytes != session["size_bytes"]:
        return create_problem_response(status_code=409, title="Object changed", detail="Staged size does not match the upload manifest.", extensions={"error_code": "OBJECT_CHANGED"})

    updated_row = PostgresImportStore.transition_staged(
        conn,
        upload_id=upload_id,
        tenant_id=current_user.tenant_id,
        destination_location=meta.ref.s3a_uri,
    )

    resp_model = _build_session_response(updated_row, import_settings, conn, current_user)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=resp_model.model_dump(mode="json"))


@router.get("/imports/{upload_id}", response_model=ImportSessionResponse)
def get_import_session(
    upload_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    import_settings: ImportSettings = Depends(get_import_settings),
) -> ImportSessionResponse:
    """Retrieve status, preview, profile, and metadata for an import session."""
    _check_import_role(current_user)

    session = PostgresImportStore.get_by_id(conn, upload_id=upload_id, tenant_id=current_user.tenant_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import session {upload_id} not found.",
        )

    return _build_session_response(session, import_settings, conn, current_user)


@router.post("/imports/{upload_id}/configure")
def configure_import_session(
    upload_id: UUID,
    req: ConfigureImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    import_settings: ImportSettings = Depends(get_import_settings),
) -> JSONResponse:
    """Apply updated column mapping and requeue session to STAGED."""
    _check_import_role(current_user)
    with conn.cursor() as cur:
        cur.execute("SELECT upload_id FROM dataset_upload_sessions WHERE upload_id=%s AND tenant_id=%s FOR UPDATE", (upload_id, current_user.tenant_id))

    session = PostgresImportStore.get_by_id(conn, upload_id=upload_id, tenant_id=current_user.tenant_id)
    if not session:
        return create_problem_response(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Import session {upload_id} not found.",
            extensions={"error_code": "RESOURCE_NOT_FOUND"},
        )

    if session.get("expires_at") and session["expires_at"] < datetime.now(session["expires_at"].tzinfo):
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Import session has expired.",
            extensions={"error_code": "IMPORT_EXPIRED"},
        )

    manifest = session.get("manifest") or {}
    error_code = manifest.get("error_code")
    allowed_statuses = ("VERIFIED",)
    is_col_error = session["status"] == "REJECTED" and error_code in (
        "DUPLICATE_COLUMN_NAME",
        "EMPTY_COLUMN_NAME",
    )

    if session["status"] not in allowed_statuses and not is_col_error:
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Session can only be reconfigured when VERIFIED or REJECTED due to column name issues.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    # Requeue to STAGED with column_names mapping in manifest
    manifest_patch = {
        "column_names_mapping": req.column_names,
        "preview": None,
        "profile": None,
        "error_code": None,
        "invalid_params": None,
    }
    updated = PostgresImportStore.update_status(
        conn,
        upload_id=upload_id,
        tenant_id=current_user.tenant_id,
        status="STAGED",
        error_reason=None,
        manifest_patch=manifest_patch,
    )

    resp_model = _build_session_response(updated, import_settings, conn, current_user)
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp_model.model_dump(mode="json"))
@router.post("/imports/{upload_id}/register", response_model=SnapshotResponse, status_code=status.HTTP_200_OK)
def register_import_snapshot(
    upload_id: UUID,
    req: RegisterImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> Any:
    """Finalize verified import session and register an immutable Dataset Snapshot."""
    _check_import_role(current_user)

    try:
        snapshot = DatasetImportService.register_snapshot(
            conn,
            upload_id=upload_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            acknowledged_warnings=req.acknowledged_warnings,
        )
        return SnapshotResponse(
            snapshot_id=snapshot.snapshot_id,
            tenant_id=snapshot.tenant_id,
            asset_id=snapshot.asset_id,
            source_kind=snapshot.source_kind,
            source_descriptor=snapshot.source_descriptor,
            schema_definition=snapshot.schema_definition,
            total_rows=snapshot.total_rows,
            total_columns=snapshot.total_columns,
            captured_at=snapshot.captured_at,
        )
    except ImportRegistrationError as exc:
        if exc.error_code == "RESOURCE_NOT_FOUND":
            return create_problem_response(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Not Found",
                detail=exc.detail,
                extensions={"error_code": "RESOURCE_NOT_FOUND"},
            )
        if exc.error_code in ("IMPORT_STATE_CONFLICT", "IMPORT_EXPIRED", "ASSET_NAME_CONFLICT", "REIMPORT_MAPPING_CONFLICT"):
            return create_problem_response(
                status_code=status.HTTP_409_CONFLICT,
                title="Conflict",
                detail=exc.detail,
                extensions={"error_code": exc.error_code},
            )
        if exc.error_code == "WARNING_ACKNOWLEDGMENT_REQUIRED":
            return create_problem_response(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Warning Acknowledgment Required",
                detail=exc.detail,
                extensions={"error_code": "WARNING_ACKNOWLEDGMENT_REQUIRED"},
            )
        return create_problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Unprocessable Entity",
            detail=exc.detail,
            extensions={"error_code": exc.error_code},
        )

@router.post("/imports/{upload_id}/abort")
def abort_import_session(
    upload_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
    store: IObjectStorePort = Depends(_get_storage_adapter),
    s3_settings: S3Settings = Depends(get_s3_settings),
    import_settings: ImportSettings = Depends(get_import_settings),
) -> JSONResponse:
    """Abort an active import session and clean up multipart upload."""
    _check_import_role(current_user)
    with conn.cursor() as cur:
        cur.execute("SELECT upload_id FROM dataset_upload_sessions WHERE upload_id=%s AND tenant_id=%s FOR UPDATE", (upload_id, current_user.tenant_id))

    session = PostgresImportStore.get_by_id(conn, upload_id=upload_id, tenant_id=current_user.tenant_id)
    if not session:
        return create_problem_response(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Import session {upload_id} not found.",
            extensions={"error_code": "RESOURCE_NOT_FOUND"},
        )

    if session["status"] not in ("INITIATED", "UPLOADING", "STAGED", "VERIFIED", "ABORTED"):
        return create_problem_response(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="Cannot abort session currently being verified by an active worker.",
            extensions={"error_code": "IMPORT_STATE_CONFLICT"},
        )

    mp_id = session.get("multipart_id")
    if mp_id and session["status"] in ("INITIATED", "UPLOADING"):
        try:
            store.abort_multipart(
                bucket=s3_settings.bucket_staging,
                key=session["staging_key"],
                multipart_id=mp_id,
            )
        except (BotoCoreError, ClientError, OSError):
            return create_problem_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                title="Storage Unavailable",
                detail="Unable to abort multipart upload; try again.",
                extensions={"error_code": "STORAGE_UNAVAILABLE"},
            )

    updated = PostgresImportStore.update_status(
        conn,
        upload_id=upload_id,
        tenant_id=current_user.tenant_id,
        status="ABORTED",
        error_reason="USER_ABORTED",
    )

    resp_model = _build_session_response(updated, import_settings, conn, current_user)
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp_model.model_dump(mode="json"))
