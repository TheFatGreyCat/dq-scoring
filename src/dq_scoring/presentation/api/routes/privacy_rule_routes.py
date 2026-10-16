"""API routes for tenant privacy detector rules (editor roles only, no DELETE)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dq_scoring.common.privacy_rules import (
    MatchMode,
    PrivacyRuleCreate,
    PrivacyRuleUpdate,
    RuleCategory,
    RuleKind,
)
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import get_current_user, get_db_connection
from dq_scoring.presentation.api.pagination import Page, Pagination, pagination
from dq_scoring.services import privacy_rule_service

router = APIRouter(prefix="/api/v1/privacy-rules", tags=["Sensitive Data & Privacy"])
RULE_EDITOR_ROLES = frozenset({"WORKSPACE_ADMIN", "DATA_OWNER", "DATA_STEWARD"})


class PrivacyRuleResponse(BaseModel):
    rule_id: UUID
    revision: int
    code: str
    kind: RuleKind
    category: RuleCategory
    enabled: bool
    builtin_code: str | None
    pattern: str | None
    match_mode: MatchMode
    case_sensitive: bool
    columns: list[str]
    created_by: UUID | None
    created_at: datetime


class PrivacyRuleWriteResponse(PrivacyRuleResponse):
    config_version: int


def _require_editor(user: AuthenticatedUser) -> None:
    if user.role not in RULE_EDITOR_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden: Role does not have permission to manage privacy detector rules")


@router.get("", response_model=Page[PrivacyRuleResponse])
def list_privacy_rules(
    paging: Pagination = Depends(pagination),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    _require_editor(current_user)
    return privacy_rule_service.list_rules(conn, current_user.tenant_id, paging)


@router.post("", status_code=201, response_model=PrivacyRuleWriteResponse)
def create_privacy_rule(
    payload: PrivacyRuleCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    _require_editor(current_user)
    return privacy_rule_service.create_rule(conn, current_user.user_id, current_user.tenant_id, payload)


@router.put("/{rule_id}", response_model=PrivacyRuleWriteResponse)
def update_privacy_rule(
    rule_id: UUID,
    payload: PrivacyRuleUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> dict:
    _require_editor(current_user)
    return privacy_rule_service.update_rule(conn, current_user.user_id, current_user.tenant_id, rule_id, payload)
