"""Single source of truth for which snapshot columns must be FULL_MASKed on output."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from uuid import UUID

import psycopg
from fastapi import HTTPException

from dq_scoring.common.privacy import SENSITIVE_CATEGORIES, mask_row


@dataclass(frozen=True)
class SnapshotProtection:
    asset_id: UUID
    policy_version: int
    scan_status: str
    scan_stale: bool
    protected_columns: frozenset[str]
    columns: tuple[dict, ...]


def column_names(schema_definition: dict | None) -> list[str]:
    return [c if isinstance(c, str) else c["name"] for c in (schema_definition or {}).get("columns", [])]


ACTIVE_FINDINGS_SQL = """(status='CONFIRMED' OR scan_id IS NOT DISTINCT FROM (
    SELECT scan_id FROM privacy_scan_jobs j
    WHERE j.tenant_id=sensitive_data_findings.tenant_id
      AND j.snapshot_id=sensitive_data_findings.snapshot_id AND purpose='APPLY' AND state='COMPLETE'
    ORDER BY created_at DESC,scan_id DESC LIMIT 1
))"""


def _scan_state(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID, manifest: dict) -> tuple[str, bool]:
    """Latest APPLY job wins; otherwise the import-time scan recorded in the manifest."""
    job = conn.execute(
        """SELECT j.state, j.config_version <> COALESCE(c.version, 0)
           FROM privacy_scan_jobs j LEFT JOIN privacy_detector_configs c ON c.tenant_id = j.tenant_id
           WHERE j.tenant_id=%s AND j.snapshot_id=%s AND j.purpose='APPLY'
           ORDER BY j.created_at DESC, j.scan_id DESC LIMIT 1""",
        (tenant_id, snapshot_id),
    ).fetchone()
    if job:
        return job[0], bool(job[1]) and job[0] == "COMPLETE"
    scan = (manifest or {}).get("sensitive_scan") or {}
    if scan.get("status") != "COMPLETE":
        return "UNAVAILABLE", False
    pinned = scan.get("config_version")
    if pinned is None:
        return "COMPLETE", False
    current = conn.execute("SELECT version FROM privacy_detector_configs WHERE tenant_id=%s", (tenant_id,)).fetchone()
    return "COMPLETE", current is not None and current[0] != pinned


def resolve_snapshot_protection(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> SnapshotProtection:
    row = conn.execute(
        "SELECT asset_id, schema_definition, manifest FROM dataset_snapshots WHERE tenant_id=%s AND snapshot_id=%s",
        (tenant_id, snapshot_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "RESOURCE_NOT_FOUND")
    asset_id, schema, manifest = row
    version = conn.execute(
        "SELECT version FROM asset_protection_revisions WHERE tenant_id=%s AND asset_id=%s", (tenant_id, asset_id)
    ).fetchone()
    declarations = {
        name: (category, reason)
        for name, category, reason in conn.execute(
            "SELECT column_name, category, reason FROM asset_column_classifications WHERE tenant_id=%s AND asset_id=%s",
            (tenant_id, asset_id),
        ).fetchall()
    }
    detected: dict[str, set[str]] = {}
    for name, category in conn.execute(
        f"""SELECT column_name, category FROM sensitive_data_findings
           WHERE tenant_id=%s AND snapshot_id=%s AND status <> 'DISMISSED' AND {ACTIVE_FINDINGS_SQL}""",
        (tenant_id, snapshot_id),
    ).fetchall():
        detected.setdefault(name, set()).add(category)
    scan_status, stale = _scan_state(conn, tenant_id, snapshot_id, manifest)
    verified = scan_status == "COMPLETE" and not stale
    columns = []
    for name in column_names(schema):
        declared, reason = declarations.get(name, (None, None))
        findings = detected.get(name, set())
        effective = findings | ({declared} if declared in SENSITIVE_CATEGORIES else set())
        protected = bool(effective) or not verified
        columns.append({
            "column_name": name, "declared_category": declared, "detected_categories": sorted(findings),
            "effective_categories": sorted(effective), "protected": protected,
            "conflict": declared == "STANDARD_DATA" and bool(findings), "reason": reason,
        })
    return SnapshotProtection(
        asset_id=asset_id,
        policy_version=version[0] if version else 0,
        scan_status=scan_status,
        scan_stale=stale,
        protected_columns=frozenset(c["column_name"] for c in columns if c["protected"]),
        columns=tuple(columns),
    )


def mask_preview_and_profile(
    preview: list | None, profile: dict | None, protected: frozenset[str]
) -> tuple[list | None, dict | None]:
    """Re-mask a stored preview and drop min/max of protected columns; counts and nulls are preserved."""
    rows = None if preview is None else [mask_row(r, protected) if isinstance(r, dict) else r for r in preview]
    if profile is None:
        return rows, None
    profile = copy.deepcopy(profile)
    for stats in profile.get("columns", []):
        if isinstance(stats, dict) and stats.get("name") in protected:
            stats.pop("min", None)
            stats.pop("max", None)
    return rows, profile


def session_protected_columns(conn: psycopg.Connection, tenant_id: UUID, row: dict) -> frozenset[str]:
    """Protected columns for an import session: current snapshot state once registered, otherwise declarations
    plus manifest findings, failing closed (all columns) without a COMPLETE scan."""
    manifest = row.get("manifest") or {}
    if row.get("registered_snapshot_id"):
        return resolve_snapshot_protection(conn, tenant_id, row["registered_snapshot_id"]).protected_columns
    scan = manifest.get("sensitive_scan") or {}
    if scan.get("status") != "COMPLETE":
        names = set(column_names({"columns": manifest.get("columns", [])}))
        for r in manifest.get("preview") or []:
            if isinstance(r, dict):
                names.update(r)
        return frozenset(names)
    protected = set(scan.get("sensitive_columns", [])) | {f["column_name"] for f in scan.get("findings") or []}
    if row.get("asset_id"):
        protected.update(
            name for (name,) in conn.execute(
                "SELECT column_name FROM asset_column_classifications WHERE tenant_id=%s AND asset_id=%s AND category = ANY(%s)",
                (tenant_id, row["asset_id"], sorted(SENSITIVE_CATEGORIES)),
            ).fetchall()
        )
    return frozenset(protected)
