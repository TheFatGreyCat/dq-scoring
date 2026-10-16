"""Tenant-scoped privacy scan submission; workers own execution and fenced publication."""
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, model_validator

from dq_scoring.common.privacy_rules import PrivacyDetectorRule, pin_rules
from dq_scoring.services.privacy_rule_service import (
    ensure_initialized,
    load_pinned_rules,
)

JOB_PROJECTION = "scan_id, snapshot_id, purpose, state, config_version, detector_digest, created_at, started_at, finished_at, error_code, result_summary"


class CreatePrivacyScan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["APPLY", "PREVIEW"]
    rule_id: UUID | None = None
    revision: int | None = None

    @model_validator(mode="after")
    def check_selection(self):
        if (self.purpose == "PREVIEW") != (self.rule_id is not None and self.revision is not None):
            raise ValueError("INVALID_PRIVACY_SCAN_SELECTION")
        if self.purpose == "APPLY" and (self.rule_id is not None or self.revision is not None):
            raise ValueError("INVALID_PRIVACY_SCAN_SELECTION")
        return self


def get_scan(conn: psycopg.Connection, tenant_id: UUID, scan_id: UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {JOB_PROJECTION} FROM privacy_scan_jobs WHERE tenant_id=%s AND scan_id=%s", (tenant_id, scan_id))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "RESOURCE_NOT_FOUND")
    return row


def create_scan(conn: psycopg.Connection, user, snapshot_id: UUID, payload: CreatePrivacyScan) -> dict:
    tenant_id = user.tenant_id
    snapshot = conn.execute("SELECT asset_id FROM dataset_snapshots WHERE tenant_id=%s AND snapshot_id=%s", (tenant_id, snapshot_id)).fetchone()
    if not snapshot:
        raise HTTPException(404, "RESOURCE_NOT_FOUND")
    conn.execute("SELECT 1 FROM data_assets WHERE tenant_id=%s AND asset_id=%s FOR UPDATE", (tenant_id, snapshot[0]))
    conn.execute("INSERT INTO asset_protection_revisions(tenant_id,asset_id,version) VALUES(%s,%s,0) ON CONFLICT DO NOTHING", (tenant_id, snapshot[0]))
    conn.execute("SELECT version FROM asset_protection_revisions WHERE tenant_id=%s AND asset_id=%s FOR UPDATE", (tenant_id, snapshot[0]))
    existing = conn.execute("SELECT scan_id,pinned_rules FROM privacy_scan_jobs WHERE tenant_id=%s AND snapshot_id=%s AND purpose=%s AND state IN ('QUEUED','RUNNING')", (tenant_id, snapshot_id, payload.purpose)).fetchone()
    if existing:
        if payload.purpose == "PREVIEW" and not any(str(r["rule_id"]) == str(payload.rule_id) and r["revision"] == payload.revision for r in existing[1]):
            raise HTTPException(409, "PRIVACY_SCAN_IN_PROGRESS")
        return get_scan(conn, tenant_id, existing[0])
    ensure_initialized(conn, tenant_id)
    pinned = load_pinned_rules(conn, tenant_id)
    if payload.purpose == "PREVIEW":
        row = conn.execute("SELECT rule_id,revision,code,kind,category,enabled,builtin_code,pattern,match_mode,case_sensitive,columns FROM privacy_detector_rules WHERE tenant_id=%s AND rule_id=%s AND revision=%s", (tenant_id,payload.rule_id,payload.revision)).fetchone()
        if not row:
            raise HTTPException(404,"RESOURCE_NOT_FOUND")
        fields = ("rule_id","revision","code","kind","category","enabled","builtin_code","pattern","match_mode","case_sensitive","columns")
        definition = dict(zip(fields,row,strict=True))
        definition["enabled"] = True
        pinned = pin_rules([PrivacyDetectorRule.model_validate(definition)], pinned.config_version)
    scan_id = uuid4()
    conn.execute("INSERT INTO privacy_scan_jobs(scan_id,tenant_id,snapshot_id,requested_by,purpose,pinned_rules,config_version,detector_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (scan_id,tenant_id,snapshot_id,user.user_id,payload.purpose,Jsonb(pinned.to_json()),pinned.config_version,pinned.digest))
    if payload.purpose == "APPLY":
        conn.execute("UPDATE asset_protection_revisions SET version=version+1 WHERE tenant_id=%s AND asset_id=%s",(tenant_id,snapshot[0]))
    return get_scan(conn,tenant_id,scan_id)
