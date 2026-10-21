"""Explicit external-LLM rule recommendations (advisory, draft-compatible, never auto-applied).

Phase 1 (short tenant transaction): authorize, resolve protection, build the allowlist context.
Phase 2: await the gateway with no DB connection or transaction open.
Phase 3 (new short transaction): revalidate protection/policy/context before returning anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from fastapi.concurrency import run_in_threadpool

from dq_scoring.adapters.llm.gateway_client import (
    AiError,
    gateway_slot,
    require_enabled,
)
from dq_scoring.adapters.llm.gateway_settings import LlmSettings
from dq_scoring.adapters.llm.recommendation_adapter import (
    PROMPT_VERSION,
    request_candidates,
    rule_content_key,
    validate_candidates,
)
from dq_scoring.common.llm_context import (
    SEMANTIC_VOCABULARY_VERSION,
    RecommendationContext,
    build_recommendation_context,
    canonical_json,
    context_sha256,
    profile_scope,
)
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    ai_http_error,
    require_active_role,
    scoped_tenant_connection,
)
from dq_scoring.services.privacy_policy import resolve_snapshot_protection
from dq_scoring.services.semantic_service import confirmed_labels

FALLBACK_CODES = frozenset({"AI_TIMEOUT", "AI_UNAVAILABLE", "AI_INVALID_OUTPUT", "AI_BUSY"})

# load(conn) -> (masked preview data incl. schema_definition/profile/total_rows, heuristic recommendation result)
Loader = Callable[[psycopg.Connection], tuple[dict, dict]]


@dataclass(frozen=True)
class _Prepared:
    state: tuple
    context: RecommendationContext
    digest: str
    payload: str
    tokens: dict[str, str]
    profile: dict
    heuristic: dict


def _prepare(conn: psycopg.Connection, user: AuthenticatedUser, snapshot_id: UUID, load: Loader, max_columns: int) -> _Prepared:
    from dq_scoring.presentation.api.routes.import_routes import ALLOWED_IMPORT_ROLES

    require_active_role(conn, user, ALLOWED_IMPORT_ROLES)
    data, heuristic = load(conn)
    protection = resolve_snapshot_protection(conn, user.tenant_id, snapshot_id)
    if protection.scan_status != "COMPLETE" or protection.scan_stale:
        raise AiError("PRIVACY_SCAN_NOT_COMPLETE")
    revision, confirmed = confirmed_labels(conn, user.tenant_id, snapshot_id)
    context, tokens = build_recommendation_context(
        data["schema_definition"], data["profile"] or {}, protection.protected_columns, data["total_rows"], max_columns, confirmed,
    )
    if context is None:
        raise AiError("AI_NO_ELIGIBLE_COLUMNS")
    payload = canonical_json(context)
    state = (revision, protection.policy_version, protection.scan_status, tuple(sorted(protection.protected_columns)),
             tuple(sorted(profile_scope(data["profile"] or {}).items(), key=str)))
    return _Prepared(state, context, context_sha256(payload), payload, tokens, data["profile"] or {}, heuristic)


def _prepare_scoped(dsn: str, user: AuthenticatedUser, snapshot_id: UUID, load: Loader, max_columns: int) -> _Prepared:
    with scoped_tenant_connection(dsn, user.tenant_id) as conn:
        return _prepare(conn, user, snapshot_id, load, max_columns)


def _tag(item: dict, source: str) -> dict:
    return {**item, "source": source}


def _merge(heuristic_rules: list[dict], ai_rules: list[dict]) -> list[dict]:
    ai_by_key = {rule_content_key(r["rule"]): r for r in ai_rules}
    merged = []
    for item in heuristic_rules:
        both = rule_content_key(item["rule"]) in ai_by_key
        merged.append(_tag(item, "HEURISTIC+LLM" if both else "HEURISTIC"))
        ai_by_key.pop(rule_content_key(item["rule"]), None)
    merged.extend(_tag(r, "LLM") for r in ai_by_key.values())
    return merged


async def recommend_with_ai(
    dsn: str, user: AuthenticatedUser, snapshot_id: UUID, engine: str, priorities: tuple[str, ...],
    settings: LlmSettings, load: Loader,
) -> dict[str, Any]:
    try:
        require_enabled(settings)
        prepared = await run_in_threadpool(_prepare_scoped, dsn, user, snapshot_id, load, settings.max_columns)
        fallback_code: str | None = None
        ai_rules: list[dict] = []
        rejected = 0
        model = str(settings.model)
        try:
            async with gateway_slot(settings):
                reply, _ = await request_candidates(settings, prepared.context)
            model = reply.model
            ai_rules, rejected = validate_candidates(reply, prepared.tokens, prepared.profile, prepared.context, priorities)
        except AiError as exc:
            if engine != "HYBRID" or exc.code not in FALLBACK_CODES:
                raise
            fallback_code = exc.code
        current = await run_in_threadpool(_prepare_scoped, dsn, user, snapshot_id, load, settings.max_columns)
        if (current.state, current.digest) != (prepared.state, prepared.digest):
            raise AiError("AI_CONTEXT_STALE")
    except AiError as exc:
        raise ai_http_error(exc.code) from None
    heuristic = prepared.heuristic
    warnings = list(heuristic.get("warnings", [])) if engine == "HYBRID" else []
    warnings.append("AI_SUGGESTIONS_ADVISORY_REQUIRE_REVIEW")
    if fallback_code:
        warnings.append(f"AI_FALLBACK_{fallback_code}")
    rules = _merge(heuristic["rules"], ai_rules) if engine == "HYBRID" else [_tag(r, "LLM") for r in ai_rules]
    if fallback_code:
        rules = _merge(heuristic["rules"], [])
    return {
        "rules": rules,
        "ruleset_templates": heuristic.get("ruleset_templates", []) if engine == "HYBRID" else [],
        "policy_templates": heuristic.get("policy_templates", []) if engine == "HYBRID" else [],
        "warnings": warnings,
        "provenance": {
            "engine": engine, "source": "HEURISTIC_FALLBACK" if fallback_code else ("HYBRID" if engine == "HYBRID" else "LLM"),
            "model": None if fallback_code else model, "prompt_version": PROMPT_VERSION,
            "context_sha256": prepared.digest, "generated_at": datetime.now(UTC).isoformat(),
            "provider": "API", "vocabulary_version": SEMANTIC_VOCABULARY_VERSION,
            "semantic_revision": prepared.state[0], "privacy_policy_version": prepared.state[1],
            "fallback": fallback_code is not None, "fallback_code": fallback_code,
            "profile": profile_scope(prepared.profile), "candidates_rejected": rejected, "columns_sent": len(prepared.context.columns),
        },
    }

