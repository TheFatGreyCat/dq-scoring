"""Tenant-owned, versioned ruleset template pack import."""
from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.presentation.api.schemas.template_pack_schemas import (
    PackTemplate,
    TemplatePack,
)

COLUMNS = (
    "template_id,template_code,name,domain,data_type,target_use_case,description,rules_payload,is_system_template,"
    "revision,provenance,examples,placeholder_schema,status,"
    "CASE WHEN payload_sha256 IS NULL THEN 'LEGACY_UNVERIFIED' ELSE 'STRUCTURAL_ONLY' END AS validation_status"
)


def template_digest(template: PackTemplate, revision: int) -> str:
    """Fingerprint of the immutable revision content, excluding users/status/timestamps."""
    return compute_deterministic_hash({"revision": revision, **template.model_dump(mode="json")})


def load_template(cur: psycopg.Cursor, template_id: UUID, tenant_id: UUID) -> dict:
    cur.execute(f"SELECT {COLUMNS} FROM ruleset_templates WHERE template_id=%s AND (tenant_id IS NULL OR tenant_id=%s)", (template_id, tenant_id))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
    item = dict(zip([column.name for column in cur.description], row, strict=True))
    if isinstance(item["rules_payload"], dict):
        item["rules_payload"] = item["rules_payload"].get("rules", [])
    return item


def import_pack(cur: psycopg.Cursor, pack: TemplatePack, tenant_id: UUID, user_id: UUID) -> dict:
    """Insert every template as a DRAFT revision in the caller's transaction; all-or-nothing.

    Concurrent imports of the same key are serialised by the unique revision index:
    ON CONFLICT DO NOTHING waits for the winner, then the digest comparison decides
    between idempotent replay and TEMPLATE_REVISION_CONFLICT.
    """
    items, created = [], 0
    for template in pack.templates:
        digest = template_digest(template, pack.revision)
        template_id = uuid4()
        cur.execute(
            "INSERT INTO ruleset_templates(template_id,tenant_id,template_code,name,domain,data_type,target_use_case,description,"
            "rules_payload,is_system_template,revision,provenance,examples,placeholder_schema,payload_sha256,status,created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s,%s,%s,'DRAFT',%s) ON CONFLICT DO NOTHING RETURNING template_id",
            (
                template_id, tenant_id, template.template_code, template.name, template.domain, template.data_type,
                template.target_use_case, template.description, Jsonb({"rules": template.rules_payload}), pack.revision,
                Jsonb(template.provenance.model_dump(mode="json")), Jsonb([example.model_dump(mode="json") for example in template.examples]),
                Jsonb({name: value.model_dump() for name, value in template.placeholder_schema.items()}), digest, user_id,
            ),
        )
        if cur.fetchone() is not None:
            created += 1
            items.append(load_template(cur, template_id, tenant_id))
            continue
        cur.execute(
            "SELECT template_id,payload_sha256 FROM ruleset_templates WHERE tenant_id=%s AND template_code=%s AND revision=%s",
            (tenant_id, template.template_code, pack.revision),
        )
        row = cur.fetchone()
        if row is None or row[1] != digest:
            raise HTTPException(409, detail="TEMPLATE_REVISION_CONFLICT")
        items.append(load_template(cur, row[0], tenant_id))
    return {"items": items, "created": created, "existing": len(items) - created}
