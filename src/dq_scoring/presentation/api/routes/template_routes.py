"""Tenant-visible template catalog, filtering and individual selection."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from dq_scoring.presentation.api import governance
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import get_current_user, get_db_connection
from dq_scoring.presentation.api.pagination import (
    Page,
    Pagination,
    contains,
    fetch_page,
    pagination,
)
from dq_scoring.presentation.api.schemas.template_pack_schemas import (
    RulesetTemplateResponse,
    TemplateImportResponse,
    TemplatePack,
)
from dq_scoring.services.template_pack_service import COLUMNS as RULESET_COLUMNS
from dq_scoring.services.template_pack_service import import_pack, load_template

TEMPLATE_AUTHOR_ROLES = frozenset({"DATA_ENGINEER", "DATA_OWNER", "DATA_STEWARD", "WORKSPACE_ADMIN"})
MAX_PACK_BYTES = 1024 * 1024

Domain = Literal["FINANCE", "RETAIL", "HEALTHCARE", "TRANSPORTATION", "GENERAL"]
TemplateStatus = Literal["DRAFT", "PENDING_APPROVAL", "ACTIVE", "DEPRECATED"]
router = APIRouter(prefix="/api/v1/templates", tags=["Rule & Scoring Templates"])


class RuleCatalogTemplateResponse(BaseModel):
    template_id: UUID
    template_code: str
    name: str
    rule_type: str
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    default_null_policy: str
    default_dimension: str
    is_advisory_default: bool


class ScoringPolicyTemplateResponse(BaseModel):
    template_id: UUID
    template_code: str
    name: str
    domain: str
    target_use_case: str
    description: str | None = None
    dimension_weights: dict[str, float] = Field(default_factory=dict)
    publication_threshold: float
    gate_rules: dict[str, Any] = Field(default_factory=dict)
    is_system_template: bool


RULE_COLUMNS = "template_id,template_code,name,rule_type,parameter_schema,default_null_policy,default_dimension,is_advisory_default"
POLICY_COLUMNS = "template_id,template_code,name,domain,target_use_case,description,dimension_weights,publication_threshold,gate_rules,is_system_template"


def _catalog(conn, user, table, projection, paging, filters):
    predicates, params = ["(tenant_id IS NULL OR tenant_id=%s)"], [user.tenant_id]
    if paging.q:
        predicates.append("(name ILIKE %s OR template_code ILIKE %s)")
        params.extend([contains(paging.q)] * 2)
    for column, value in filters:
        if value is not None:
            predicates.append(f"{column}=%s")
            params.append(value)
    result = fetch_page(conn, projection=projection, source=table, predicates=predicates, params=params, order="template_code,template_id", paging=paging)
    for item in result["items"]:
        if "rules_payload" in item and isinstance(item["rules_payload"], dict):
            item["rules_payload"] = item["rules_payload"].get("rules", [])
    return result


@router.get("/rules", response_model=Page[RuleCatalogTemplateResponse])
def list_rule_templates(rule_type: Literal["NON_NULL", "TYPE_PARSE", "DOMAIN_RANGE", "CROSS_FIELD", "UNIQUENESS", "TEXT_QUALITY", "SPELLING", "JSON_FIELD", "JSON_ARRAY"] | None = None, dimension: Literal["COMPLETENESS", "ACCURACY", "CONSISTENCY", "TIMELINESS", "UNIQUENESS", "VALIDITY"] | None = None, paging: Pagination = Depends(pagination), current_user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    return _catalog(conn, current_user, "rule_catalog_templates", RULE_COLUMNS, paging, [("rule_type", rule_type), ("default_dimension", dimension)])


def _require_author(user: AuthenticatedUser) -> None:
    if user.role not in TEMPLATE_AUTHOR_ROLES:
        raise HTTPException(403, detail="Forbidden: Role cannot manage ruleset templates")


@router.get("/rulesets", response_model=Page[RulesetTemplateResponse])
def list_ruleset_templates(domain: Domain | None = None, data_type: Literal["TRANSACTION_EVENT", "MASTER_DATA", "DIMENSION_TABLE", "TIMESERIES"] | None = None, status: TemplateStatus = "ACTIVE", paging: Pagination = Depends(pagination), current_user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    if status != "ACTIVE":
        _require_author(current_user)
    return _catalog(conn, current_user, "ruleset_templates", RULESET_COLUMNS, paging, [("domain", domain), ("data_type", data_type), ("status", status)])


@router.post("/rulesets/import", response_model=TemplateImportResponse)
async def import_ruleset_templates(request: Request, current_user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    _require_author(current_user)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_PACK_BYTES:
            raise HTTPException(413, detail="TEMPLATE_PACK_TOO_LARGE")
    try:
        pack = TemplatePack.model_validate_json(bytes(body))
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors(include_url=False, include_context=False, include_input=False)) from exc
    with conn.cursor() as cur:
        return import_pack(cur, pack, current_user.tenant_id, current_user.user_id)


def _governed_template(template_id: UUID, user: AuthenticatedUser, conn: psycopg.Connection, action) -> dict:
    _require_author(user)
    with conn.cursor() as cur:
        try:
            action(cur, governance.TEMPLATES, template_id, user)
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, detail="TEMPLATE_ACTIVE_REVISION_CONFLICT") from None
        return load_template(cur, template_id, user.tenant_id)


@router.post("/rulesets/{template_id}/submit", response_model=RulesetTemplateResponse)
def submit_ruleset_template(template_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    return _governed_template(template_id, user, conn, governance.submit_for_approval)


@router.post("/rulesets/{template_id}/approve", response_model=RulesetTemplateResponse)
def approve_ruleset_template(template_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    return _governed_template(template_id, user, conn, governance.approve)


@router.get("/policies", response_model=Page[ScoringPolicyTemplateResponse])
def list_policy_templates(domain: Domain | None = None, paging: Pagination = Depends(pagination), current_user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    return _catalog(conn, current_user, "scoring_policy_templates", POLICY_COLUMNS, paging, [("domain", domain)])


def _detail(conn, user, table, projection, template_id):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {projection} FROM {table} WHERE template_id=%s AND (tenant_id IS NULL OR tenant_id=%s)", (template_id, user.tenant_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
        item = dict(zip([c.name for c in cur.description], row, strict=True))
        if "rules_payload" in item and isinstance(item["rules_payload"], dict):
            item["rules_payload"] = item["rules_payload"].get("rules", [])
        return item


@router.get("/rulesets/{template_id}", response_model=RulesetTemplateResponse)
def get_ruleset_template(template_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    with conn.cursor() as cur:
        item = load_template(cur, template_id, user.tenant_id)
    if item["status"] != "ACTIVE" and user.role not in TEMPLATE_AUTHOR_ROLES:
        raise HTTPException(404, detail="RESOURCE_NOT_FOUND")
    return item


@router.get("/policies/{template_id}", response_model=ScoringPolicyTemplateResponse)
def get_policy_template(template_id: UUID, user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    return _detail(conn, user, "scoring_policy_templates", POLICY_COLUMNS, template_id)


@router.get("/overview")
def get_template_overview(user: AuthenticatedUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_db_connection)):
    counts = {}
    with conn.cursor() as cur:
        for kind, table in (("rule", "rule_catalog_templates"), ("ruleset", "ruleset_templates"), ("policy", "scoring_policy_templates")):
            active = " AND status='ACTIVE'" if table == "ruleset_templates" else ""
            cur.execute(f"SELECT count(*) FROM {table} WHERE (tenant_id IS NULL OR tenant_id=%s){active}", (user.tenant_id,))
            counts[f"total_{kind}_templates"] = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT domain FROM ruleset_templates WHERE (tenant_id IS NULL OR tenant_id=%s) AND status='ACTIVE' ORDER BY domain", (user.tenant_id,))
        counts["supported_domains"] = [row[0] for row in cur.fetchall()]
    return counts
