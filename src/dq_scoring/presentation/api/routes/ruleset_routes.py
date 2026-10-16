"""Ruleset configuration and independent approval routes (AC-003)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from dq_scoring.adapters.compute.spelling_dictionary import SpellingDictionaryManager
from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.presentation.api import governance
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import (
    check_tenant_access,
    get_current_user,
    get_db_connection,
)
from dq_scoring.presentation.api.pagination import (
    Page,
    Pagination,
    contains,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.ruleset_schemas import (
    ApproveRulesetRequest,
    CreateRulesetRequest,
    QualityRuleResponse,
    RulesetResponse,
    SubmitRulesetRequest,
)

router = APIRouter(prefix="/api/v1/rulesets", tags=["Rulesets & Approval Workflow"])


@router.post("", response_model=RulesetResponse, status_code=status.HTTP_201_CREATED)
def create_ruleset(
    req: CreateRulesetRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> RulesetResponse:
    """Create a new Ruleset in DRAFT status with quality rules."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tenant_id FROM data_assets WHERE asset_id = %s;",
            (req.asset_id,),
        )
        asset_row = cur.fetchone()
        if not asset_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target Data Asset not found.",
            )
        check_tenant_access(asset_row[0], current_user.tenant_id)

        cur.execute(
            "SELECT s.schema_definition FROM data_assets a JOIN dataset_snapshots s ON s.snapshot_id=a.current_snapshot_id AND s.tenant_id=a.tenant_id WHERE a.asset_id=%s AND a.tenant_id=%s",
            (req.asset_id, current_user.tenant_id),
        )
        snapshot_row = cur.fetchone()
        columns = (snapshot_row[0].get("columns", []) if snapshot_row else [])
        structured = {column["name"] for column in columns if isinstance(column, dict) and column.get("structural_encoding") == "JSON"}
        for rule in req.rules:
            target = rule.parameters.get("column", rule.parameters.get("target_column"))
            if rule.rule_type in ("JSON_FIELD", "JSON_ARRAY"):
                if snapshot_row is None:
                    raise HTTPException(422, detail="SNAPSHOT_REQUIRED_FOR_STRUCTURED_RULE")
                if target not in structured:
                    raise HTTPException(422, detail="STRUCTURED_COLUMN_REQUIRES_JSON_RULE")
            elif rule.rule_type in ("TYPE_PARSE", "DOMAIN_RANGE", "CROSS_FIELD", "TEXT_QUALITY", "SPELLING"):
                if target in structured or rule.parameters.get("comparison_column") in structured:
                    raise HTTPException(422, detail="STRUCTURED_COLUMN_REQUIRES_JSON_RULE")
            if rule.rule_type == "SPELLING":
                try:
                    rule.parameters["dictionary_digests"] = SpellingDictionaryManager().get_digests(
                        rule.parameters["dictionary_revision"], rule.parameters["language"],
                    )
                except ValueError as exc:
                    raise HTTPException(422, detail="TEXT_DICTIONARY_UNAVAILABLE") from exc

        ruleset_id = uuid4()
        now = datetime.now(UTC)
        version_str = f"1.0.0-{ruleset_id.hex[:6]}"

        rules_data = [r.model_dump(mode="json") for r in req.rules]
        rules_hash = compute_deterministic_hash(rules_data)

        cur.execute(
            """
            INSERT INTO rulesets (
                ruleset_id, tenant_id, asset_id, name, version, config_hash,
                status, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'DRAFT', %s, %s);
            """,
            (
                ruleset_id,
                current_user.tenant_id,
                req.asset_id,
                req.name,
                version_str,
                rules_hash,
                current_user.user_id,
                now,
            ),
        )

        saved_rules: list[QualityRuleResponse] = []
        for r in req.rules:
            rule_id = uuid4()
            target_col = r.parameters.get("column", r.parameters.get("target_column", "*"))
            score_enabled = False if r.is_advisory else r.score_enabled
            weight = 0.0 if r.is_advisory else r.contribution_weight
            cur.execute(
                """
                INSERT INTO quality_rules (
                    rule_id, tenant_id, ruleset_id, rule_name, dimension,
                    target_column, rule_type, parameters, null_policy, weight, severity,
                    is_advisory, is_required, gate_enabled, score_enabled,
                    acceptance_threshold, source
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, 'USER'
                );
                """,
                (
                    rule_id,
                    current_user.tenant_id,
                    ruleset_id,
                    r.rule_code,
                    r.dimension.upper(),
                    target_col,
                    r.rule_type.upper(),
                    Jsonb(r.parameters),
                    r.null_policy.upper(),
                    weight,
                    "CRITICAL" if r.is_critical else "STANDARD",
                    r.is_advisory,
                    r.is_required,
                    r.gate_enabled,
                    score_enabled,
                    r.acceptance_threshold,
                ),
            )
            saved_rules.append(
                QualityRuleResponse(
                    rule_id=rule_id,
                    rule_code=r.rule_code,
                    dimension=r.dimension,
                    rule_type=r.rule_type,
                    parameters=r.parameters,
                    null_policy=r.null_policy,
                    is_required=r.is_required,
                    is_critical=r.is_critical,
                    gate_enabled=r.gate_enabled,
                    score_enabled=score_enabled,
                    contribution_weight=weight,
                    acceptance_threshold=r.acceptance_threshold,
                    is_advisory=r.is_advisory,
                )
            )

        return RulesetResponse(
            ruleset_id=ruleset_id,
            tenant_id=current_user.tenant_id,
            asset_id=req.asset_id,
            name=req.name,
            status="DRAFT",
            current_version=1,
            created_by=current_user.user_id,
            created_at=now,
            rules=saved_rules,
        )

def _ruleset_response(cur: psycopg.Cursor, ruleset_id: UUID) -> RulesetResponse:
    """Build the response from what is stored, never from request echoes."""
    cur.execute(
        """
        SELECT ruleset_id, tenant_id, asset_id, COALESCE(name, version), status, created_by, created_at
        FROM rulesets WHERE ruleset_id = %s;
        """,
        (ruleset_id,),
    )
    rs = cur.fetchone()
    cur.execute(
        """
        SELECT rule_id, rule_name, dimension, rule_type, parameters, null_policy, is_required,
               severity = 'CRITICAL', gate_enabled, score_enabled, weight, acceptance_threshold, is_advisory
        FROM quality_rules WHERE ruleset_id = %s ORDER BY rule_name;
        """,
        (ruleset_id,),
    )
    rules = [
        QualityRuleResponse(
            rule_id=r[0], rule_code=r[1], dimension=r[2], rule_type=r[3], parameters=r[4] or {},
            null_policy=r[5].lower(), is_required=r[6], is_critical=r[7], gate_enabled=r[8],
            score_enabled=r[9], contribution_weight=r[10], acceptance_threshold=r[11], is_advisory=r[12],
        )
        for r in cur.fetchall()
    ]
    return RulesetResponse(
        ruleset_id=rs[0], tenant_id=rs[1], asset_id=rs[2], name=rs[3], status=rs[4],
        current_version=1, created_by=rs[5], created_at=rs[6], rules=rules,
    )


@router.get("", response_model=Page[RulesetResponse])
def list_rulesets(asset_id: UUID | None = None, status: Literal["DRAFT", "PENDING_APPROVAL", "ACTIVE", "DEPRECATED"] | None = None, paging: Pagination = Depends(pagination), user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)) -> dict:
    predicates, params = ["tenant_id=%s"], [user.tenant_id]
    if paging.q:
        predicates.append("COALESCE(name,version) ILIKE %s")
        params.append(contains(paging.q))
    for column, value in (("asset_id", asset_id), ("status", status)):
        if value is not None:
            predicates.append(f"{column}=%s")
            params.append(value)
    result = fetch_page(conn, projection="ruleset_id", source="rulesets", predicates=predicates, params=params, order="created_at DESC,ruleset_id DESC", paging=paging)
    with conn.cursor() as cur:
        result["items"] = [_ruleset_response(cur, row["ruleset_id"]) for row in result["items"]]
    return result


@router.get("/{ruleset_id}", response_model=RulesetResponse)
def get_ruleset(ruleset_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)) -> RulesetResponse:
    with conn.cursor() as cur:
        cur.execute("SELECT ruleset_id FROM rulesets WHERE tenant_id=%s AND ruleset_id=%s", (user.tenant_id, ruleset_id))
        if not cur.fetchone():
            raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
        return _ruleset_response(cur, ruleset_id)


@router.post("/{ruleset_id}/submit", response_model=RulesetResponse)
def submit_ruleset(
    ruleset_id: UUID,
    req: SubmitRulesetRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> RulesetResponse:
    """Submit a DRAFT ruleset revision for independent approval (DRAFT -> PENDING_APPROVAL)."""
    with conn.cursor() as cur:
        governance.submit_for_approval(cur, governance.RULESETS, ruleset_id, current_user)
        return _ruleset_response(cur, ruleset_id)


@router.post("/{ruleset_id}/approve", response_model=RulesetResponse)
def approve_ruleset(
    ruleset_id: UUID,
    req: ApproveRulesetRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> RulesetResponse:
    """AC-003 & FR-GOV-006: Approve a PENDING_APPROVAL ruleset (creator/submitter != approver)."""
    with conn.cursor() as cur:
        governance.approve(cur, governance.RULESETS, ruleset_id, current_user)
        return _ruleset_response(cur, ruleset_id)
