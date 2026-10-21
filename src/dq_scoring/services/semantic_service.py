"""Column semantic state (user-confirmed business labels) and explicit, advisory semantic inference.

Inference mirrors recommend_with_ai: short DB transaction, awaited gateway call with no DB connection open,
then revalidation. Candidates are never persisted; only an explicit confirmation writes state.
Semantic labels never alter privacy classification.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from psycopg.rows import dict_row

from dq_scoring.adapters.llm.gateway_client import AiError, gateway_slot
from dq_scoring.adapters.llm.gateway_settings import LlmSettings
from dq_scoring.adapters.llm.semantic_adapter import (
    PROMPT_VERSION,
    request_semantic,
    validate_semantics,
)
from dq_scoring.common.llm_context import canonical_json, context_sha256, profile_scope
from dq_scoring.common.semantic_context import (
    SEMANTIC_VOCABULARY_VERSION,
    build_api_context,
    build_local_context,
    local_evidence,
)
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    ai_http_error,
    require_active_role,
    scoped_tenant_connection,
)
from dq_scoring.services.privacy_policy import column_names, resolve_snapshot_protection
from dq_scoring.services.snapshot_profile_service import load_snapshot

Provider = Literal["LOCAL", "API"]
# load(conn) -> masked data: schema_definition, profile (selected mode, protected extrema dropped), total_rows
Loader = Callable[[psycopg.Connection], dict]


class SemanticError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _write_roles() -> frozenset[str]:
    from dq_scoring.presentation.api.routes.import_routes import ALLOWED_IMPORT_ROLES

    return ALLOWED_IMPORT_ROLES


def load_confirmed(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> tuple[int, dict[str, dict]]:
    """Current snapshot revision and confirmed rows keyed by column."""
    row = conn.execute(
        "SELECT revision FROM snapshot_semantic_state WHERE tenant_id=%s AND snapshot_id=%s", (tenant_id, snapshot_id)
    ).fetchone()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT column_name,label,revision,updated_by,updated_at,reason FROM snapshot_column_semantics "
            "WHERE tenant_id=%s AND snapshot_id=%s ORDER BY column_name",
            (tenant_id, snapshot_id),
        )
        rows = {r["column_name"]: r for r in cur.fetchall()}
    return (row[0] if row else 0), rows


def confirmed_labels(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> tuple[int, dict[str, str]]:
    revision, rows = load_confirmed(conn, tenant_id, snapshot_id)
    return revision, {name: r["label"] for name, r in rows.items()}


def semantic_view(conn: psycopg.Connection, user: AuthenticatedUser, snapshot_id: UUID, data: dict) -> dict:
    """Local evidence next to the confirmed projection; no model involved."""
    protection = resolve_snapshot_protection(conn, user.tenant_id, snapshot_id)
    revision, rows = load_confirmed(conn, user.tenant_id, snapshot_id)
    columns = []
    for item in local_evidence(data["schema_definition"], data["profile"], list(protection.columns)):
        confirmed = rows.get(item["column"])
        columns.append({
            **item, "protected": item["column"] in protection.protected_columns,
            "confirmed": None if confirmed is None else {k: confirmed[k] for k in ("label", "revision", "updated_by", "updated_at", "reason")},
        })
    return {"vocabulary_version": SEMANTIC_VOCABULARY_VERSION, "revision": revision, "columns": columns}


def apply_confirmations(
    conn: psycopg.Connection, user: AuthenticatedUser, snapshot_id: UUID,
    expected_revision: int, reason: str, changes: list[tuple[str, str | None]],
) -> dict:
    """Atomic in the caller's transaction: revision bump, state rows and append-only history together."""
    require_active_role(conn, user, _write_roles())
    names = column_names(load_snapshot(conn, user.tenant_id, snapshot_id).schema_definition)
    seen: set[str] = set()
    for column, _ in changes:
        if column not in names or column in seen:
            raise SemanticError("SEMANTIC_COLUMN_INVALID")
        seen.add(column)
    tenant = user.tenant_id
    conn.execute(
        "INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (tenant, snapshot_id)
    )
    locked = conn.execute(
        "SELECT revision FROM snapshot_semantic_state WHERE tenant_id=%s AND snapshot_id=%s FOR UPDATE", (tenant, snapshot_id)
    ).fetchone()[0]
    if locked != expected_revision:
        raise SemanticError("SEMANTIC_REVISION_CONFLICT")
    current = dict(conn.execute(
        "SELECT column_name,label FROM snapshot_column_semantics WHERE tenant_id=%s AND snapshot_id=%s AND column_name = ANY(%s)",
        (tenant, snapshot_id, [c for c, _ in changes]),
    ).fetchall())
    effective = [(c, label) for c, label in changes if label is not None or c in current]
    if not effective:
        return {"revision": locked, "changed": 0}
    bumped = conn.execute(
        "UPDATE snapshot_semantic_state SET revision=revision+1 WHERE tenant_id=%s AND snapshot_id=%s RETURNING revision",
        (tenant, snapshot_id),
    ).fetchone()
    revision = bumped[0]
    for column, label in effective:
        if label is None:
            conn.execute(
                "DELETE FROM snapshot_column_semantics WHERE tenant_id=%s AND snapshot_id=%s AND column_name=%s", (tenant, snapshot_id, column)
            )
        else:
            conn.execute(
                "INSERT INTO snapshot_column_semantics(tenant_id,snapshot_id,column_name,label,revision,updated_by,reason) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,snapshot_id,column_name) DO UPDATE SET "
                "label=EXCLUDED.label,revision=EXCLUDED.revision,updated_by=EXCLUDED.updated_by,updated_at=clock_timestamp(),reason=EXCLUDED.reason",
                (tenant, snapshot_id, column, label, revision, user.user_id, reason),
            )
        conn.execute(
            "INSERT INTO snapshot_column_semantic_history(tenant_id,snapshot_id,revision,column_name,action,label,previous_label,actor_user_id,reason) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tenant, snapshot_id, revision, column, "RESET" if label is None else "CONFIRM", label, current.get(column), user.user_id, reason),
        )
    return {"revision": revision, "changed": len(effective)}


@dataclass(frozen=True)
class _Prepared:
    state: tuple
    context: Any
    digest: str
    tokens: dict[str, str]
    profile: dict


def _prepare(conn: psycopg.Connection, user: AuthenticatedUser, snapshot_id: UUID, provider: Provider, load: Loader, max_columns: int) -> _Prepared:
    require_active_role(conn, user, _write_roles())
    data = load(conn)
    protection = resolve_snapshot_protection(conn, user.tenant_id, snapshot_id)
    if protection.scan_status != "COMPLETE" or protection.scan_stale:
        raise AiError("PRIVACY_SCAN_NOT_COMPLETE")
    revision, confirmed = confirmed_labels(conn, user.tenant_id, snapshot_id)
    build = build_local_context if provider == "LOCAL" else build_api_context
    profile = data["profile"] or {}
    context, tokens = build(data["schema_definition"], profile, protection.protected_columns, confirmed, max_columns)
    if context is None:
        raise AiError("AI_NO_ELIGIBLE_COLUMNS")
    state = (provider, revision, protection.policy_version, protection.scan_status, tuple(sorted(protection.protected_columns)),
             tuple(sorted(profile_scope(profile).items(), key=str)))
    return _Prepared(state, context, context_sha256(canonical_json(context)), tokens, profile)


def _prepare_scoped(dsn: str, user: AuthenticatedUser, snapshot_id: UUID, provider: Provider, load: Loader, max_columns: int) -> _Prepared:
    with scoped_tenant_connection(dsn, user.tenant_id) as conn:
        return _prepare(conn, user, snapshot_id, provider, load, max_columns)


async def infer_semantics(
    dsn: str, user: AuthenticatedUser, snapshot_id: UUID, provider: Provider, settings: LlmSettings, load: Loader,
) -> dict[str, Any]:
    """Explicit inference for ONE chosen provider; any failure is returned as such, never retried elsewhere."""
    try:
        if not (settings.enabled and settings.configured):
            raise AiError("AI_NOT_CONFIGURED")
        prepared = await run_in_threadpool(_prepare_scoped, dsn, user, snapshot_id, provider, load, settings.max_columns)
        async with gateway_slot(settings):
            reply, _ = await request_semantic(settings, prepared.context)
        candidates, rejected = validate_semantics(reply, prepared.tokens, prepared.context)
        try:
            current = await run_in_threadpool(_prepare_scoped, dsn, user, snapshot_id, provider, load, settings.max_columns)
        except (HTTPException, AiError):
            raise AiError("AI_CONTEXT_STALE") from None
        if (current.state, current.digest) != (prepared.state, prepared.digest):
            raise AiError("AI_CONTEXT_STALE")
    except AiError as exc:
        raise ai_http_error(exc.code) from None
    return {
        "candidates": [{**item, "source": provider} for item in candidates],
        "rejected": rejected,
        "provenance": {
            "provider": provider, "model": reply.model, "prompt_version": PROMPT_VERSION,
            "vocabulary_version": SEMANTIC_VOCABULARY_VERSION, "context_sha256": prepared.digest,
            "semantic_revision": prepared.state[1], "privacy_policy_version": prepared.state[2],
            "generated_at": datetime.now(UTC).isoformat(),
            "profile": profile_scope(prepared.profile), "columns_sent": len(prepared.context.columns),
        },
    }
