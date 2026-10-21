"""Admin self-approval of rulesets/policies (plan 2026-10-17, Task 3).

Contract under test: a WORKSPACE_ADMIN who created/submitted a ruleset or scoring policy may approve it
themselves only while PENDING_APPROVAL, only with an explicit non-blank bounded `self_approval_reason`, and
the approval plus its audit row commit atomically. Everyone else keeps the independent-approval rule, and
ruleset *templates* are unaffected.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.auth import hash_password
from tests.support.object_snapshots import register_snapshot_via_api

PWD = "SecretPassword123!"
PWD_HASH = hash_password(PWD)
REASON = "Sole workspace admin; reviewed the configuration against the data contract."

KINDS = {
    "rulesets": {"id": "ruleset_id", "table": "rulesets", "resource_type": "RULESET"},
    "policies": {"id": "policy_id", "table": "scoring_policies", "resource_type": "SCORING_POLICY"},
}
BOTH = pytest.mark.parametrize("kind", list(KINDS))


@dataclass
class Actor:
    user_id: UUID
    headers: dict[str, str] = field(repr=False)


@dataclass
class World:
    client: TestClient
    db: object
    tenant_id: UUID
    asset_id: str

    def actor(self, role: str, tenant_id: UUID | None = None) -> Actor:
        tenant_id = tenant_id or self.tenant_id
        user_id = uuid4()
        email = f"{role.lower()}_{user_id.hex[:8]}@example.com"
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id,email,password_hash,full_name,is_active) VALUES (%s,%s,%s,%s,TRUE)",
                (user_id, email, PWD_HASH, role),
            )
            cur.execute(
                "INSERT INTO tenant_memberships (tenant_id,user_id,role,status) VALUES (%s,%s,%s,'ACTIVE')",
                (tenant_id, user_id, role),
            )
        self.db.commit()
        resp = self.client.post("/api/v1/auth/login", json={"email": email, "password": PWD, "tenant_id": str(tenant_id)})
        assert resp.status_code == 200
        return Actor(user_id, {"Authorization": f"Bearer {resp.json()['access_token']}"})

    def create(self, kind: str, actor: Actor, asset_id: str | None = None) -> str:
        if kind == "rulesets":
            body = {
                "asset_id": asset_id or self.asset_id,
                "name": f"Ruleset {uuid4().hex[:6]}",
                "rules": [{"rule_code": "R_ID", "dimension": "Completeness", "rule_type": "NON_NULL", "parameters": {"column": "id"}, "is_required": True}],
            }
        else:
            body = {"name": f"Policy {uuid4().hex[:6]}", "gate_fail_threshold": 60.0, "gate_warn_threshold": 80.0, "min_coverage_threshold": 0.8, "critical_acceptance_threshold": 95.0}
        resp = self.client.post(f"/api/v1/{kind}", headers=actor.headers, json=body)
        assert resp.status_code == 201, resp.text
        return resp.json()[KINDS[kind]["id"]]

    def submit(self, kind: str, entity_id: str, actor: Actor) -> None:
        resp = self.client.post(f"/api/v1/{kind}/{entity_id}/submit", headers=actor.headers, json={})
        assert resp.status_code == 200, resp.text

    def pending(self, kind: str, creator: Actor, submitter: Actor | None = None, asset_id: str | None = None) -> str:
        entity_id = self.create(kind, creator, asset_id)
        self.submit(kind, entity_id, submitter or creator)
        return entity_id

    def approve(self, kind: str, entity_id: str, actor: Actor, body: dict | None = None, client: TestClient | None = None):
        return (client or self.client).post(f"/api/v1/{kind}/{entity_id}/approve", headers=actor.headers, json=body or {})

    def row(self, kind: str, entity_id: str) -> tuple:
        with self.db.cursor() as cur:
            cur.execute(f"SELECT status, approved_by FROM {KINDS[kind]['table']} WHERE {KINDS[kind]['id']}=%s", (entity_id,))
            row = cur.fetchone()
        self.db.commit()
        return row

    def audit(self, entity_id: str) -> list[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, actor_user_id, action, resource_type, event_timestamp, diff_json "
                "FROM audit_logs WHERE resource_id=%s ORDER BY event_timestamp, audit_id",
                (entity_id,),
            )
            rows = cur.fetchall()
        self.db.commit()
        return [dict(zip(("tenant_id", "actor", "action", "resource_type", "at", "diff"), r, strict=True)) for r in rows]


@pytest.fixture
def world(client: TestClient, db_conn) -> World:
    tenant_id = uuid4()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s,%s,%s,'ENTERPRISE','ACTIVE')",
            (tenant_id, f"org_{tenant_id.hex[:8]}", "Self Approval Org"),
        )
    db_conn.commit()
    w = World(client, db_conn, tenant_id, "")
    owner = w.actor("DATA_OWNER")
    resp = client.post("/api/v1/assets", headers=owner.headers, json={"name": f"Asset {uuid4().hex[:6]}"})
    assert resp.status_code == 201
    w.asset_id = resp.json()["asset_id"]
    return w


@BOTH
def test_admin_creator_self_approves_with_reason_and_atomic_audit(world: World, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    entity_id = world.pending(kind, admin)

    resp = world.approve(kind, entity_id, admin, {"self_approval_reason": f"  {REASON}  "})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ACTIVE"
    assert world.row(kind, entity_id) == ("ACTIVE", admin.user_id)
    (entry,) = world.audit(entity_id)
    assert entry["tenant_id"] == world.tenant_id
    assert entry["actor"] == admin.user_id
    assert entry["action"] == "APPROVE"
    assert entry["resource_type"] == KINDS[kind]["resource_type"]
    diff = entry["diff"]
    assert diff["self_approval"] is True
    assert diff["reason"] == REASON
    assert diff["revision"]["version"] and diff["revision"]["config_hash"]
    assert diff["before"]["status"] == "PENDING_APPROVAL"
    assert diff["after"]["status"] == "ACTIVE"
    assert diff["after"]["approved_by"] == str(admin.user_id)
    assert diff["created_by"] == diff["submitted_by"] == str(admin.user_id)
    assert entry["at"] is not None


def test_self_approved_configuration_can_run_and_gate_is_unchanged(world: World):
    admin = world.actor("WORKSPACE_ADMIN")
    snap = register_snapshot_via_api(world.client, admin.headers, content_or_path=b"id,fare\n1,12\n", asset_id=world.asset_id, process_full_profile=True)
    ruleset_id = world.pending("rulesets", admin)
    policy_id = world.pending("policies", admin)
    run_body = {"snapshot_id": snap["snapshot_id"], "ruleset_id": ruleset_id, "policy_id": policy_id, "idempotency_key": f"self-{uuid4()}"}

    assert world.client.post("/api/v1/runs", headers=admin.headers, json=run_body).status_code == 422
    assert world.approve("rulesets", ruleset_id, admin, {"self_approval_reason": REASON}).status_code == 200
    assert world.approve("policies", policy_id, admin, {"self_approval_reason": REASON}).status_code == 200

    run = world.client.post("/api/v1/runs", headers=admin.headers, json=run_body)
    assert run.status_code == 202, run.text
    assert run.json()["status"] == "QUEUED"


@BOTH
def test_admin_who_only_submitted_may_self_approve(world: World, kind: str):
    steward = world.actor("DATA_STEWARD")
    admin = world.actor("WORKSPACE_ADMIN")
    entity_id = world.pending(kind, steward, submitter=admin)

    resp = world.approve(kind, entity_id, admin, {"self_approval_reason": REASON})

    assert resp.status_code == 200, resp.text
    (entry,) = world.audit(entity_id)
    assert entry["diff"]["self_approval"] is True
    assert entry["diff"]["created_by"] == str(steward.user_id)
    assert entry["diff"]["submitted_by"] == str(admin.user_id)


@BOTH
@pytest.mark.parametrize("body", [{}, {"approval_notes": "looks fine"}, {"self_approval_reason": ""}, {"self_approval_reason": "   \n\t"}, {"self_approval_reason": "x" * 501}])
def test_self_approval_requires_nonblank_bounded_reason(world: World, kind: str, body: dict):
    admin = world.actor("WORKSPACE_ADMIN")
    entity_id = world.pending(kind, admin)

    resp = world.approve(kind, entity_id, admin, body)

    assert resp.status_code == 422
    assert world.row(kind, entity_id) == ("PENDING_APPROVAL", None)
    assert world.audit(entity_id) == []


@BOTH
@pytest.mark.parametrize("role", ["DATA_STEWARD", "DATA_OWNER", "DATA_ENGINEER"])
def test_non_admin_creator_or_submitter_still_denied_even_with_reason(world: World, kind: str, role: str):
    actor = world.actor(role)
    entity_id = world.pending(kind, actor)

    resp = world.approve(kind, entity_id, actor, {"self_approval_reason": REASON})

    assert resp.status_code == 403
    assert "Independent approval violation" in resp.json()["detail"]
    assert world.row(kind, entity_id) == ("PENDING_APPROVAL", None)
    assert world.audit(entity_id) == []


@BOTH
def test_non_approver_role_denied_and_reason_grants_nothing(world: World, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    viewer = world.actor("BUSINESS_VIEWER")
    entity_id = world.pending(kind, admin)

    resp = world.approve(kind, entity_id, viewer, {"self_approval_reason": REASON})

    assert resp.status_code == 403
    assert world.row(kind, entity_id) == ("PENDING_APPROVAL", None)


@BOTH
@pytest.mark.parametrize("membership", ["DATA_OWNER", "SUSPENDED"])
def test_stale_admin_token_cannot_self_approve(world: World, kind: str, membership: str):
    admin = world.actor("WORKSPACE_ADMIN")
    entity_id = world.pending(kind, admin)
    with world.db.cursor() as cur:
        if membership == "SUSPENDED":
            cur.execute("UPDATE tenant_memberships SET status='SUSPENDED' WHERE tenant_id=%s AND user_id=%s", (world.tenant_id, admin.user_id))
        else:
            cur.execute("UPDATE tenant_memberships SET role=%s WHERE tenant_id=%s AND user_id=%s", (membership, world.tenant_id, admin.user_id))
    world.db.commit()
    response = world.approve(kind, entity_id, admin, {"self_approval_reason": REASON})
    assert response.status_code == 403
    assert world.row(kind, entity_id) == ("PENDING_APPROVAL", None)
    assert world.audit(entity_id) == []
    listing = world.client.get(f"/api/v1/{kind}", headers=admin.headers)
    if listing.status_code == 200:
        item = next(item for item in listing.json()["items"] if item[KINDS[kind]["id"]] == entity_id)
        assert item["can_self_approve"] is False


@BOTH
def test_wrong_state_is_rejected_even_for_eligible_admin(world: World, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    draft_id = world.create(kind, admin)

    draft = world.approve(kind, draft_id, admin, {"self_approval_reason": REASON})
    assert draft.status_code == 400
    assert world.row(kind, draft_id) == ("DRAFT", None)

    active_id = world.pending(kind, admin)
    assert world.approve(kind, active_id, admin, {"self_approval_reason": REASON}).status_code == 200
    again = world.approve(kind, active_id, admin, {"self_approval_reason": REASON})
    assert again.status_code == 400
    assert len(world.audit(active_id)) == 1


@BOTH
def test_independent_approval_still_works_and_is_audited_as_not_self(world: World, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    owner = world.actor("DATA_OWNER")
    entity_id = world.pending(kind, admin)

    resp = world.approve(kind, entity_id, owner, {"approval_notes": "ok", "self_approval_reason": "not applicable"})

    assert resp.status_code == 200, resp.text
    (entry,) = world.audit(entity_id)
    assert entry["actor"] == owner.user_id
    assert entry["diff"]["self_approval"] is False
    assert entry["diff"]["reason"] is None


@BOTH
def test_other_tenant_admin_cannot_approve(world: World, db_conn, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    entity_id = world.pending(kind, admin)
    other_tenant = uuid4()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s,%s,%s,'ENTERPRISE','ACTIVE')",
            (other_tenant, f"org_{other_tenant.hex[:8]}", "Other Org"),
        )
    db_conn.commit()
    outsider = world.actor("WORKSPACE_ADMIN", other_tenant)

    resp = world.approve(kind, entity_id, outsider, {"self_approval_reason": REASON})

    assert resp.status_code in (403, 404)
    assert world.row(kind, entity_id) == ("PENDING_APPROVAL", None)
    assert world.audit(entity_id) == []


def test_template_governance_keeps_independent_approval(world: World, db_conn):
    admin = world.actor("WORKSPACE_ADMIN")
    template_id = uuid4()
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ruleset_templates (template_id, tenant_id, template_code, name, domain, data_type, target_use_case,
                                           rules_payload, is_system_template, status, created_by, submitted_by, submitted_at)
            VALUES (%s,%s,%s,'Tenant template','GENERAL','MASTER_DATA','TABULAR_QUALITY','{"rules": []}'::jsonb,FALSE,
                    'PENDING_APPROVAL',%s,%s,now())
            """,
            (template_id, world.tenant_id, f"TPL_{template_id.hex[:6]}", admin.user_id, admin.user_id),
        )
    db_conn.commit()

    resp = world.client.post(
        f"/api/v1/templates/rulesets/{template_id}/approve",
        headers=admin.headers,
        json={"self_approval_reason": REASON},
    )

    assert resp.status_code == 403
    assert "Independent approval violation" in resp.json()["detail"]
    with db_conn.cursor() as cur:
        cur.execute("SELECT status, approved_by FROM ruleset_templates WHERE template_id=%s", (template_id,))
        assert cur.fetchone() == ("PENDING_APPROVAL", None)
    assert world.audit(str(template_id)) == []


@BOTH
def test_self_approval_supersedes_previous_active_and_records_it(world: World, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    owner = world.actor("DATA_OWNER")
    first = world.pending(kind, owner)
    assert world.approve(kind, first, admin).status_code == 200
    second = world.pending(kind, admin)

    assert world.approve(kind, second, admin, {"self_approval_reason": REASON}).status_code == 200

    assert world.row(kind, first)[0] == "DEPRECATED"
    assert world.row(kind, second)[0] == "ACTIVE"
    assert [str(i) for i in world.audit(second)[0]["diff"]["superseded_ids"]] == [first]


@BOTH
def test_audit_failure_rolls_back_approval_and_supersession(world: World, db_conn, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    owner = world.actor("DATA_OWNER")
    first = world.pending(kind, owner)
    assert world.approve(kind, first, admin).status_code == 200
    second = world.pending(kind, admin)
    with db_conn.cursor() as cur:
        cur.execute("CREATE FUNCTION fail_audit_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit unavailable'; END $$;")
        cur.execute("CREATE TRIGGER fail_audit_insert BEFORE INSERT ON audit_logs FOR EACH ROW EXECUTE FUNCTION fail_audit_insert();")
    db_conn.commit()
    try:
        resp = world.approve(kind, second, admin, {"self_approval_reason": REASON}, client=TestClient(world.client.app, raise_server_exceptions=False))
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DROP TRIGGER fail_audit_insert ON audit_logs;")
            cur.execute("DROP FUNCTION fail_audit_insert();")
        db_conn.commit()

    assert resp.status_code >= 500
    assert world.row(kind, second) == ("PENDING_APPROVAL", None)
    assert world.row(kind, first)[0] == "ACTIVE"
    assert world.audit(second) == []


def _post_together(world: World, calls: list[tuple[str, str, Actor]]) -> list:
    barrier = Barrier(len(calls))

    def go(call):
        kind, entity_id, actor = call
        client = TestClient(world.client.app)
        barrier.wait()
        return world.approve(kind, entity_id, actor, {"self_approval_reason": REASON}, client=client)

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(go, calls))


@BOTH
def test_concurrent_double_approval_succeeds_exactly_once(world: World, kind: str):
    admin = world.actor("WORKSPACE_ADMIN")
    entity_id = world.pending(kind, admin)

    responses = _post_together(world, [(kind, entity_id, admin)] * 2)

    assert sorted(r.status_code for r in responses) == [200, 400]
    assert world.row(kind, entity_id) == ("ACTIVE", admin.user_id)
    assert len(world.audit(entity_id)) == 1


@BOTH
def test_concurrent_approvals_in_one_scope_leave_exactly_one_active(world: World, db_conn, kind: str):
    admin_a = world.actor("WORKSPACE_ADMIN")
    admin_b = world.actor("WORKSPACE_ADMIN")
    first = world.pending(kind, admin_a)
    second = world.pending(kind, admin_b)

    responses = _post_together(world, [(kind, first, admin_a), (kind, second, admin_b)])

    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    statuses = sorted([world.row(kind, first)[0], world.row(kind, second)[0]])
    assert statuses == ["ACTIVE", "DEPRECATED"]
    assert len(world.audit(first)) == len(world.audit(second)) == 1
