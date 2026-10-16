"""Template pack import, versioning and governance through the public API (synthetic data only)."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from dq_scoring.presentation.api.auth import hash_password
from tests.integration.conftest import PASSWORD, _login, client  # noqa: F401

DOWN_SQL = Path(__file__).resolve().parents[3] / "src/dq_scoring/adapters/db/migrations/018_template_provenance_down.sql"
PROVENANCE = {
    "kind": "ENGINEERING_CONVENTION", "source_uri": "repo://packs/synthetic", "source_title": "Synthetic pack",
    "source_version": "1", "source_section": "all", "retrieved_at": "2026-01-01T00:00:00Z",
    "license": "internal", "applicability": "synthetic tests only",
}


def _template(code: str, description: str = "synthetic") -> dict:
    expected = lambda outcome: {"NOT_BLANK": outcome}
    return {
        "template_code": code, "name": code, "domain": "GENERAL", "data_type": "MASTER_DATA", "target_use_case": "TEST",
        "description": description, "provenance": PROVENANCE, "placeholder_schema": {"$col": {"type": "COLUMN"}},
        "rules_payload": [{"rule_code": "NOT_BLANK", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "$col"}}],
        "examples": [
            {"input": {"id": "a"}, "bindings": {"$col": "id"}, "expected": expected("passed")},
            {"input": {"id": ""}, "bindings": {"$col": "id"}, "expected": expected("missing")},
        ],
    }


def _pack(*templates: dict, revision: int = 1) -> dict:
    return {"pack_code": "synthetic", "revision": revision, "templates": list(templates)}


def _user(db_conn, tenant_id: UUID, role: str) -> str:
    user_id = uuid4()
    email = f"{role.lower()}_{user_id.hex[:8]}@example.com"
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s,%s,%s,'Synthetic User',TRUE)", (user_id, email, hash_password(PASSWORD)))
        cur.execute("INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s,%s,%s,'ACTIVE')", (tenant_id, user_id, role))
    db_conn.commit()
    return email


@pytest.fixture
def org(client, db_conn):  # noqa: F811
    """Tenant with engineer, steward and viewer sessions."""
    tenant_id = uuid4()
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s,%s,'Template Org','ENTERPRISE','ACTIVE')", (tenant_id, f"tpl_{tenant_id.hex[:8]}"))
    db_conn.commit()
    sessions = {role: _login(client, _user(db_conn, tenant_id, role), tenant_id) for role in ("DATA_ENGINEER", "DATA_STEWARD", "BUSINESS_VIEWER")}
    return {"tenant_id": tenant_id, **sessions}


def _import(http_client, headers, pack):
    return http_client.post("/api/v1/templates/rulesets/import", headers=headers, json=pack)


def test_import_creates_tenant_owned_drafts_and_is_idempotent(client, org):  # noqa: F811
    code = f"T_{uuid4().hex[:8]}"
    first = _import(client, org["DATA_ENGINEER"], _pack(_template(code)))
    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["created"], body["existing"]) == (1, 0)
    item = body["items"][0]
    assert (item["status"], item["revision"], item["is_system_template"], item["validation_status"]) == ("DRAFT", 1, False, "STRUCTURAL_ONLY")
    assert item["provenance"]["kind"] == "ENGINEERING_CONVENTION" and item["placeholder_schema"] == {"$col": {"type": "COLUMN", "required": True}}
    replay = _import(client, org["DATA_ENGINEER"], _pack(_template(code))).json()
    assert (replay["created"], replay["existing"], replay["items"][0]["template_id"]) == (0, 1, item["template_id"])


def test_changed_payload_conflicts_and_import_is_all_or_nothing(client, org):  # noqa: F811
    code, fresh = f"T_{uuid4().hex[:8]}", f"T_{uuid4().hex[:8]}"
    assert _import(client, org["DATA_ENGINEER"], _pack(_template(code))).status_code == 200
    conflict = _import(client, org["DATA_ENGINEER"], _pack(_template(fresh), _template(code, "changed")))
    assert conflict.status_code == 409 and conflict.json()["detail"] == "TEMPLATE_REVISION_CONFLICT"
    drafts = client.get("/api/v1/templates/rulesets?status=DRAFT&page_size=100", headers=org["DATA_ENGINEER"]).json()["items"]
    assert fresh not in {item["template_code"] for item in drafts}
    assert _import(client, org["DATA_ENGINEER"], _pack(_template(code, "changed"), revision=2)).json()["created"] == 1


def test_concurrent_identical_imports_never_500(client, org):  # noqa: F811
    pack, results = _pack(_template(f"T_{uuid4().hex[:8]}")), []
    barrier = threading.Barrier(6)

    def run():
        barrier.wait()
        response = _import(client, org["DATA_ENGINEER"], pack)
        results.append((response.status_code, response.json().get("created")))

    threads = [threading.Thread(target=run) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(code for code, _ in results) == [200] * 6, results
    assert sum(created for _, created in results) == 1


def test_import_rejections_do_not_echo_input(client, org):  # noqa: F811
    secret = "SYNTHETIC-SECRET-4242"
    broken = _template(f"T_{uuid4().hex[:8]}")
    broken["rules_payload"][0]["parameters"][secret] = secret
    response = _import(client, org["DATA_ENGINEER"], _pack(broken))
    assert response.status_code == 422 and secret not in response.text
    nested = _template(f"T_{uuid4().hex[:8]}")
    nested["rules_payload"][0] = {**nested["rules_payload"][0], "rule_type": "DOMAIN_RANGE", "parameters": {"column": "$col", "allowed_values": ["$col"]}}
    assert _import(client, org["DATA_ENGINEER"], _pack(nested)).status_code == 422
    assert _import(client, org["BUSINESS_VIEWER"], _pack(_template("X"))).status_code == 403
    oversized = client.post("/api/v1/templates/rulesets/import", headers=org["DATA_ENGINEER"], content=b" " * (1024 * 1024 + 1))
    assert oversized.status_code == 413
    assert client.post("/api/v1/templates/rulesets/import", headers=org["DATA_ENGINEER"], content=b"{").status_code == 422


def test_governance_visibility_and_isolation(client, org, db_conn):  # noqa: F811
    code = f"T_{uuid4().hex[:8]}"
    item = _import(client, org["DATA_ENGINEER"], _pack(_template(code))).json()["items"][0]
    tid = item["template_id"]
    other = {"DATA_ENGINEER": _login(client, _user(db_conn, _new_tenant(db_conn), "DATA_ENGINEER"), _last_tenant[0])}

    def codes(headers, status=None):
        suffix = f"?status={status}&page_size=100" if status else "?page_size=100"
        return {t["template_code"] for t in client.get(f"/api/v1/templates/rulesets{suffix}", headers=headers).json()["items"]}

    assert code not in codes(org["BUSINESS_VIEWER"]) and code not in codes(org["DATA_ENGINEER"])
    assert code in codes(org["DATA_ENGINEER"], "DRAFT")
    assert client.get("/api/v1/templates/rulesets?status=DRAFT", headers=org["BUSINESS_VIEWER"]).status_code == 403
    assert client.get(f"/api/v1/templates/rulesets/{tid}", headers=org["BUSINESS_VIEWER"]).status_code == 404
    assert client.get(f"/api/v1/templates/rulesets/{tid}", headers=other["DATA_ENGINEER"]).status_code == 404
    for action in ("submit", "approve"):
        assert client.post(f"/api/v1/templates/rulesets/{tid}/{action}", headers=other["DATA_ENGINEER"]).status_code == 404
    assert code not in codes(other["DATA_ENGINEER"], "DRAFT")
    assert client.post(f"/api/v1/templates/rulesets/{tid}/approve", headers=org["DATA_STEWARD"]).status_code == 400
    assert client.post(f"/api/v1/templates/rulesets/{tid}/submit", headers=org["BUSINESS_VIEWER"]).status_code == 403
    submitted = client.post(f"/api/v1/templates/rulesets/{tid}/submit", headers=org["DATA_ENGINEER"])
    assert submitted.status_code == 200 and submitted.json()["status"] == "PENDING_APPROVAL"
    assert client.post(f"/api/v1/templates/rulesets/{tid}/approve", headers=org["DATA_ENGINEER"]).status_code == 403
    approved = client.post(f"/api/v1/templates/rulesets/{tid}/approve", headers=org["DATA_STEWARD"])
    assert approved.status_code == 200 and approved.json()["status"] == "ACTIVE"
    assert code in codes(org["BUSINESS_VIEWER"]) and code not in codes(other["DATA_ENGINEER"])
    assert client.get(f"/api/v1/templates/rulesets/{tid}", headers=org["BUSINESS_VIEWER"]).status_code == 200


def test_independent_approval_blocks_the_importing_steward(client, org):  # noqa: F811
    tid = _import(client, org["DATA_STEWARD"], _pack(_template(f"T_{uuid4().hex[:8]}"))).json()["items"][0]["template_id"]
    assert client.post(f"/api/v1/templates/rulesets/{tid}/submit", headers=org["DATA_STEWARD"]).status_code == 200
    assert client.post(f"/api/v1/templates/rulesets/{tid}/approve", headers=org["DATA_STEWARD"]).status_code == 403


def test_approving_new_revision_supersedes_previous_active(client, org):  # noqa: F811
    code = f"T_{uuid4().hex[:8]}"
    ids = []
    for revision in (1, 2):
        tid = _import(client, org["DATA_ENGINEER"], _pack(_template(code), revision=revision)).json()["items"][0]["template_id"]
        assert client.post(f"/api/v1/templates/rulesets/{tid}/submit", headers=org["DATA_ENGINEER"]).status_code == 200
        assert client.post(f"/api/v1/templates/rulesets/{tid}/approve", headers=org["DATA_STEWARD"]).status_code == 200
        ids.append(tid)
    active = [t for t in client.get("/api/v1/templates/rulesets?page_size=100", headers=org["BUSINESS_VIEWER"]).json()["items"] if t["template_code"] == code]
    assert [(t["template_id"], t["revision"]) for t in active] == [(ids[1], 2)]
    assert client.get(f"/api/v1/templates/rulesets/{ids[0]}", headers=org["DATA_ENGINEER"]).json()["status"] == "DEPRECATED"


def test_rollback_refuses_to_drop_governed_metadata(client, org, db_conn):  # noqa: F811
    _import(client, org["DATA_ENGINEER"], _pack(_template(f"T_{uuid4().hex[:8]}")))
    with pytest.raises(psycopg.errors.RaiseException, match="Cannot rollback 018"):
        db_conn.execute(DOWN_SQL.read_text())
    db_conn.rollback()


_last_tenant: list[UUID] = []


def _new_tenant(db_conn) -> UUID:
    tenant_id = uuid4()
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s,%s,'Other Org','ENTERPRISE','ACTIVE')", (tenant_id, f"oth_{tenant_id.hex[:8]}"))
    db_conn.commit()
    _last_tenant[:] = [tenant_id]
    return tenant_id
