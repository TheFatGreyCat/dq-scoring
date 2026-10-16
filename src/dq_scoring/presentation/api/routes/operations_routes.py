"""Admin infrastructure views and tenant-scoped overview."""

from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from dq_scoring.adapters.compute.spark_settings import SparkSettings
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.storage.s3_settings import get_import_settings, get_s3_settings
from dq_scoring.common.protected_transport import protected_connect
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    PrivilegedSessionError,
    get_current_user,
    get_db_connection,
    get_pg_dsn,
    validate_api_session,
)
from dq_scoring.presentation.api.routes.import_routes import (
    ALLOWED_IMPORT_ROLES,
    _build_session_response,
)
from dq_scoring.presentation.api.schemas.import_schemas import ImportSessionSummary
from dq_scoring.presentation.api.schemas.operations_schemas import (
    Components,
    MonitorResponse,
    QueueSummary,
    SparkSummary,
)
from dq_scoring.services.operations_service import monitor_snapshot, storage_status

router = APIRouter(prefix="/api/v1", tags=["Operations"])


def require_operations_admin(user: AuthenticatedUser = Depends(get_current_user)):
    if user.role != "WORKSPACE_ADMIN":
        raise HTTPException(403, "Operations access requires a workspace administrator")
    return user


@router.get("/operations/monitor", response_model=MonitorResponse)
def monitor(
    user=Depends(require_operations_admin),
    dsn=Depends(get_pg_dsn),
    storage=Depends(get_s3_settings),
):
    storage_health = storage_status(storage, user.tenant_id)
    try:
        with protected_connect(
            dsn, connect_timeout=2, options="-c statement_timeout=2000"
        ) as conn:
            validate_api_session(conn)
            conn.execute("SET LOCAL ROLE dq_app_role")
            set_tenant_context(conn, user.tenant_id)
            return monitor_snapshot(conn, user.tenant_id, storage_health)
    except PrivilegedSessionError:
        raise HTTPException(
            403, "Privileged database sessions are not permitted"
        ) from None
    except psycopg.Error:
        return MonitorResponse(
            checked_at=datetime.now(UTC),
            components=Components(database="down", storage=storage_health),
            workers=[],
            spark=SparkSummary(),
            queue=QueueSummary(),
        )


@router.get("/operations/config")
def deployment_config(user=Depends(require_operations_admin), dsn=Depends(get_pg_dsn)):
    imports = get_import_settings()
    sizing = SparkSettings()
    snapshot = monitor(user, dsn, get_s3_settings())
    return {
        "configured_only": True,
        "imports": {
            "formats": ["CSV", "PARQUET", "JSONL"],
            **{
                key: getattr(imports, key)
                for key in ("max_bytes", "part_bytes", "max_columns")
            },
        },
        "deployment": {
            key: getattr(sizing, key)
            for key in (
                "driver_memory",
                "executor_memory",
                "executor_instances",
                "executor_cores",
                "max_memory_mb",
                "sql_shuffle_partitions",
            )
        },
        "reported_workers": [
            {"worker_id": w.worker_id, "sizing": w.metrics.sizing}
            for w in snapshot.workers
            if w.status != "stale" and w.metrics.sizing
        ],
    }


@router.get("/overview")
def overview(user=Depends(get_current_user), conn=Depends(get_db_connection)):
    tenant = user.tenant_id

    def count(table, extra=""):
        return conn.execute(
            f"SELECT count(*) FROM {table} WHERE tenant_id=%s {extra}", (tenant,)
        ).fetchone()[0]

    statuses = ("QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
    runs = {
        status: count("evaluation_runs", f"AND run_status='{status}'")
        for status in statuses
    }
    recent = conn.execute(
        "SELECT r.run_id,r.tenant_id,r.snapshot_id,r.ruleset_id,r.policy_id,r.run_status,r.created_at,r.completed_at,a.assessment_id FROM evaluation_runs r LEFT JOIN assessments a ON a.tenant_id=r.tenant_id AND a.run_id=r.run_id WHERE r.tenant_id=%s ORDER BY r.created_at DESC,r.run_id DESC LIMIT 5",
        (tenant,),
    ).fetchall()
    keys = (
        "run_id",
        "tenant_id",
        "snapshot_id",
        "ruleset_id",
        "policy_id",
        "status",
        "created_at",
        "completed_at",
        "assessment_id",
    )
    result = {
        "checked_at": datetime.now(UTC),
        "counts": {
            "assets": count("data_assets"),
            "snapshots": count("dataset_snapshots"),
            "runs": runs,
            "rulesets_pending": count("rulesets", "AND status='PENDING_APPROVAL'"),
            "policies_pending": count(
                "scoring_policies", "AND status='PENDING_APPROVAL'"
            ),
        },
        "recent_runs": [dict(zip(keys, row, strict=True)) for row in recent],
        "import_counts": None,
        "recent_imports": None,
    }
    if user.role in ALLOWED_IMPORT_ROLES:
        result["import_counts"] = {
            status: count("dataset_upload_sessions", f"AND status='{status}'")
            for status in ("STAGED", "VERIFYING", "VERIFIED", "REJECTED", "FAILED")
        }
        imports = conn.execute(
            "SELECT upload_id,status,asset_id,asset_name,format,original_filename,size_bytes,registered_snapshot_id,created_at,updated_at,expires_at,manifest,error_reason FROM dataset_upload_sessions WHERE tenant_id=%s ORDER BY created_at DESC,upload_id DESC LIMIT 5",
            (tenant,),
        ).fetchall()
        import_keys = (
            "upload_id",
            "status",
            "asset_id",
            "asset_name",
            "format",
            "original_filename",
            "size_bytes",
            "registered_snapshot_id",
            "created_at",
            "updated_at",
            "expires_at",
            "manifest",
            "error_reason",
        )
        result["recent_imports"] = [
            ImportSessionSummary.model_validate(_build_session_response(
                dict(zip(import_keys, row, strict=True)), get_import_settings(), conn, user
            ).model_dump()) for row in imports
        ]
    return result
