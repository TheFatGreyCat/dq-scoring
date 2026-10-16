"""Tenant-scoped privacy detector rules: append-only revisions under a per-tenant config lock.

Callers own the transaction (tenant context + RLS role already set on `conn`). Audit events carry rule
identifiers and flags only, never patterns or column scopes.
"""
from __future__ import annotations

from uuid import UUID, uuid4, uuid5

import psycopg
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from dq_scoring.common.privacy_rules import (
    BUILTIN_RULE_CATEGORIES,
    MAX_ENABLED_RULES,
    PRIVACY_RULE_NAMESPACE,
    PinnedPrivacyRules,
    PrivacyDetectorRule,
    PrivacyRuleCreate,
    PrivacyRuleUpdate,
    pin_rules,
)
from dq_scoring.presentation.api.pagination import Pagination, contains, fetch_page

RULE_COLUMNS = "rule_id, revision, code, kind, category, enabled, builtin_code, pattern, match_mode, case_sensitive, columns, created_by, created_at"
_LATEST = "(SELECT DISTINCT ON (rule_id) * FROM privacy_detector_rules WHERE tenant_id = %s ORDER BY rule_id, revision DESC)"


def builtin_rule_id(tenant_id: UUID, builtin_code: str) -> UUID:
    return uuid5(PRIVACY_RULE_NAMESPACE, f"{tenant_id}:{builtin_code}")


def _row(row, config_version: int | None = None) -> dict:
    names = [c.strip() for c in RULE_COLUMNS.split(",")]
    item = dict(zip(names, row, strict=True))
    if config_version is not None:
        item["config_version"] = config_version
    return item


def ensure_initialized(conn: psycopg.Connection, tenant_id: UUID) -> None:
    """Lazy-seed the nine builtin rules (revision 1) and config version 1 for a tenant, once, race-free."""
    if conn.execute("SELECT 1 FROM privacy_detector_configs WHERE tenant_id=%s", (tenant_id,)).fetchone():
        return
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"privacy-rules:{tenant_id}",))
    if conn.execute("SELECT 1 FROM privacy_detector_configs WHERE tenant_id=%s", (tenant_id,)).fetchone():
        return
    for code, category in BUILTIN_RULE_CATEGORIES.items():
        conn.execute(
            "INSERT INTO privacy_detector_rules(tenant_id, rule_id, revision, code, kind, category, enabled, builtin_code) "
            "VALUES (%s, %s, 1, %s, 'BUILTIN', %s, TRUE, %s) ON CONFLICT DO NOTHING",
            (tenant_id, builtin_rule_id(tenant_id, code), code, category, code),
        )
    conn.execute("INSERT INTO privacy_detector_configs(tenant_id, version) VALUES (%s, 1) ON CONFLICT DO NOTHING", (tenant_id,))


def _lock_config(conn: psycopg.Connection, tenant_id: UUID) -> int:
    ensure_initialized(conn, tenant_id)
    return conn.execute("SELECT version FROM privacy_detector_configs WHERE tenant_id=%s FOR UPDATE", (tenant_id,)).fetchone()[0]


def _enabled_count(conn: psycopg.Connection, tenant_id: UUID) -> int:
    return conn.execute(f"SELECT count(*) FROM {_LATEST} r WHERE r.enabled", (tenant_id,)).fetchone()[0]


def _bump(conn: psycopg.Connection, tenant_id: UUID, version: int) -> int:
    conn.execute("UPDATE privacy_detector_configs SET version=%s WHERE tenant_id=%s", (version + 1, tenant_id))
    return version + 1


def _audit(conn: psycopg.Connection, tenant_id: UUID, user_id: UUID, action: str, before: dict | None, after: dict) -> None:
    conn.execute(
        "INSERT INTO privacy_change_events(event_id, tenant_id, actor_user_id, action, before_state, after_state) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (uuid4(), tenant_id, user_id, action, Jsonb(before) if before else None, Jsonb(after)),
    )


def _state(item: dict, config_version: int) -> dict:
    return {
        "rule_id": str(item["rule_id"]), "revision": item["revision"], "code": item["code"], "kind": item["kind"],
        "category": item["category"], "enabled": item["enabled"], "config_version": config_version,
    }


def list_rules(conn: psycopg.Connection, tenant_id: UUID, paging: Pagination) -> dict:
    ensure_initialized(conn, tenant_id)
    params: list = [tenant_id]
    predicates = ["TRUE"]
    if paging.q:
        predicates, params = ["r.code ILIKE %s"], [tenant_id, contains(paging.q)]
    page = fetch_page(
        conn, projection=RULE_COLUMNS, source=f"{_LATEST} r", predicates=predicates, params=params,
        order="r.code", paging=paging,
    )
    return page


def create_rule(conn: psycopg.Connection, user_id: UUID, tenant_id: UUID, payload: PrivacyRuleCreate) -> dict:
    version = _lock_config(conn, tenant_id)
    if conn.execute("SELECT 1 FROM privacy_detector_rules WHERE tenant_id=%s AND code=%s LIMIT 1", (tenant_id, payload.code)).fetchone():
        raise HTTPException(409, "PRIVACY_RULE_CODE_CONFLICT")
    if payload.enabled and _enabled_count(conn, tenant_id) >= MAX_ENABLED_RULES:
        raise HTTPException(422, "PRIVACY_RULE_LIMIT_EXCEEDED")
    row = conn.execute(
        f"INSERT INTO privacy_detector_rules(tenant_id, rule_id, revision, code, kind, category, enabled, pattern, match_mode, case_sensitive, columns, created_by) "
        f"VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {RULE_COLUMNS}",
        (tenant_id, uuid4(), payload.code, payload.kind, payload.category, payload.enabled, payload.pattern,
         payload.match_mode, payload.case_sensitive, Jsonb(payload.columns), user_id),
    ).fetchone()
    new_version = _bump(conn, tenant_id, version)
    item = _row(row, new_version)
    _audit(conn, tenant_id, user_id, "PRIVACY_RULE_CREATED", None, _state(item, new_version))
    return item


def update_rule(conn: psycopg.Connection, user_id: UUID, tenant_id: UUID, rule_id: UUID, payload: PrivacyRuleUpdate) -> dict:
    version = _lock_config(conn, tenant_id)
    current = conn.execute(
        f"SELECT {RULE_COLUMNS} FROM privacy_detector_rules WHERE tenant_id=%s AND rule_id=%s ORDER BY revision DESC LIMIT 1",
        (tenant_id, rule_id),
    ).fetchone()
    if not current:
        raise HTTPException(404, "RESOURCE_NOT_FOUND")
    previous = _row(current)
    if previous["revision"] != payload.expected_revision:
        raise HTTPException(409, "PRIVACY_RULE_REVISION_CONFLICT")
    if (previous["kind"] == "BUILTIN") != (payload.pattern is None):
        raise HTTPException(422, "INVALID_PRIVACY_RULE")
    if payload.enabled and not previous["enabled"] and _enabled_count(conn, tenant_id) >= MAX_ENABLED_RULES:
        raise HTTPException(422, "PRIVACY_RULE_LIMIT_EXCEEDED")
    row = conn.execute(
        f"INSERT INTO privacy_detector_rules(tenant_id, rule_id, revision, code, kind, category, enabled, builtin_code, pattern, match_mode, case_sensitive, columns, created_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {RULE_COLUMNS}",
        (tenant_id, rule_id, previous["revision"] + 1, previous["code"], previous["kind"], payload.category,
         payload.enabled, previous["builtin_code"], payload.pattern, payload.match_mode, payload.case_sensitive,
         Jsonb(payload.columns), user_id),
    ).fetchone()
    new_version = _bump(conn, tenant_id, version)
    item = _row(row, new_version)
    _audit(conn, tenant_id, user_id, "PRIVACY_RULE_REVISED", _state(previous, version), _state(item, new_version))
    return item


def load_pinned_rules(conn: psycopg.Connection, tenant_id: UUID) -> PinnedPrivacyRules:
    """Latest enabled rules + config version from ONE statement (single snapshot), for scans and imports.

    Lazy-seeds a tenant without config, which needs INSERT privilege (dq_app_role); read-only roles only
    work for tenants already seeded by migration 020 or a prior API call.
    """
    ensure_initialized(conn, tenant_id)
    rows = conn.execute(
        f"WITH latest AS {_LATEST} "
        f"SELECT c.version, {', '.join('l.' + c.strip() for c in RULE_COLUMNS.split(','))} "
        "FROM privacy_detector_configs c LEFT JOIN latest l ON l.enabled WHERE c.tenant_id = %s",
        (tenant_id, tenant_id),
    ).fetchall()
    version = rows[0][0]
    rules = [
        PrivacyDetectorRule(
            rule_id=r[1], revision=r[2], code=r[3], kind=r[4], category=r[5], enabled=r[6], builtin_code=r[7],
            pattern=r[8], match_mode=r[9], case_sensitive=r[10], columns=tuple(r[11]),
        )
        for r in rows if r[1] is not None
    ]
    return pin_rules(rules, version)
