"""Tenant-scoped, versioned asset column declarations."""
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from dq_scoring.services.privacy_policy import column_names, resolve_snapshot_protection


def get_classifications(conn, tenant_id, snapshot_id):
    p = resolve_snapshot_protection(conn, tenant_id, snapshot_id)
    return {"asset_id": p.asset_id, "snapshot_id": snapshot_id, "version": p.policy_version, "scan_status": p.scan_status, "scan_stale": p.scan_stale, "columns": list(p.columns)}


def update_classifications(conn, user, asset_id, payload):
    tenant_id = user.tenant_id
    asset = conn.execute("SELECT asset_id FROM data_assets WHERE tenant_id=%s AND asset_id=%s FOR UPDATE", (tenant_id, asset_id)).fetchone()
    if not asset:
        raise HTTPException(404, "RESOURCE_NOT_FOUND")
    snapshot = conn.execute("SELECT schema_definition FROM dataset_snapshots WHERE tenant_id=%s AND asset_id=%s AND snapshot_id=%s", (tenant_id, asset_id, payload.snapshot_id)).fetchone()
    if not snapshot:
        raise HTTPException(404, "RESOURCE_NOT_FOUND")
    names = set(column_names(snapshot[0]))
    if any(change.column_name not in names for change in payload.changes):
        raise HTTPException(422, "INVALID_CLASSIFICATION_COLUMN")
    conn.execute("INSERT INTO asset_protection_revisions(tenant_id,asset_id,version) VALUES(%s,%s,0) ON CONFLICT DO NOTHING", (tenant_id, asset_id))
    version = conn.execute("SELECT version FROM asset_protection_revisions WHERE tenant_id=%s AND asset_id=%s FOR UPDATE", (tenant_id, asset_id)).fetchone()[0]
    if version != payload.expected_version:
        raise HTTPException(409, "POLICY_VERSION_CONFLICT")
    for change in payload.changes:
        previous = conn.execute("SELECT category FROM asset_column_classifications WHERE tenant_id=%s AND asset_id=%s AND column_name=%s", (tenant_id, asset_id, change.column_name)).fetchone()
        if change.category is None:
            conn.execute("DELETE FROM asset_column_classifications WHERE tenant_id=%s AND asset_id=%s AND column_name=%s", (tenant_id, asset_id, change.column_name))
        else:
            conn.execute("INSERT INTO asset_column_classifications(tenant_id,asset_id,column_name,category,updated_by,reason) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,asset_id,column_name) DO UPDATE SET category=EXCLUDED.category,updated_by=EXCLUDED.updated_by,reason=EXCLUDED.reason,updated_at=now()", (tenant_id, asset_id, change.column_name, change.category, user.user_id, change.reason))
        conn.execute("INSERT INTO privacy_change_events(event_id,tenant_id,asset_id,snapshot_id,actor_user_id,action,before_state,after_state,reason) VALUES(%s,%s,%s,%s,%s,'CLASSIFICATION_CHANGED',%s,%s,%s)", (uuid4(), tenant_id, asset_id, payload.snapshot_id, user.user_id, Jsonb({"column_name": change.column_name, "category": previous[0] if previous else None, "version": version}), Jsonb({"column_name": change.column_name, "category": change.category, "version": version + 1}), change.reason))
    conn.execute("UPDATE asset_protection_revisions SET version=version+1 WHERE tenant_id=%s AND asset_id=%s", (tenant_id, asset_id))
    return get_classifications(conn, tenant_id, payload.snapshot_id)
