"""API regression tests for defects found in the repository audit (synthetic data only)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from dq_scoring.core.entities import DatasetSnapshot
from tests.integration.conftest import Tenant

PASSWORD = "Synthetic-Password-123!"
FIXTURE_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "audit" / "tiny.csv"

def _snapshot(client: TestClient, t: Tenant) -> tuple[str, str]:
    from tests.support.object_snapshots import register_snapshot_via_api
    snap = register_snapshot_via_api(
        client,
        t.creator,
        content_or_path=FIXTURE_CSV,
        file_format="CSV",
        filename="tiny.csv",
    )
    return snap["asset_id"], snap["snapshot_id"]


def _active_ruleset(client: TestClient, t: Tenant, asset_id: str) -> str:
    rs = client.post(
        "/api/v1/rulesets",
        headers=t.creator,
        json={
            "asset_id": asset_id,
            "name": "Audit ruleset",
            "rules": [
                {"rule_code": "R_COMP", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "amount"}, "is_required": True},
            ],
        },
    )
    assert rs.status_code == 201, rs.text
    rs_id = rs.json()["ruleset_id"]
    assert client.post(f"/api/v1/rulesets/{rs_id}/submit", headers=t.creator, json={}).status_code == 200
    approved = client.post(f"/api/v1/rulesets/{rs_id}/approve", headers=t.approver, json={})
    assert approved.status_code == 200, approved.text
    return rs_id


def _active_policy(client: TestClient, t: Tenant, **overrides: object) -> str:
    body = {"name": "Audit policy", **overrides}
    pol = client.post("/api/v1/policies", headers=t.creator, json=body)
    assert pol.status_code == 201, pol.text
    pol_id = pol.json()["policy_id"]
    assert client.post(f"/api/v1/policies/{pol_id}/submit", headers=t.creator, json={}).status_code == 200
    approved = client.post(f"/api/v1/policies/{pol_id}/approve", headers=t.approver, json={})
    assert approved.status_code == 200, approved.text
    return pol_id


def test_run_uses_the_approved_policy_settings(client: TestClient, tenant: Tenant, db_conn) -> None:
    """C1: thresholds, coverage and weights from the approved policy reach the queued RunSpec."""
    asset_id, snapshot_id = _snapshot(client, tenant)
    ruleset_id = _active_ruleset(client, tenant, asset_id)
    policy_id = _active_policy(
        client,
        tenant,
        gate_fail_threshold=10.0,
        gate_warn_threshold=20.0,
        min_coverage_threshold=0.5,
        critical_acceptance_threshold=95.0,
        dimension_weights={"Completeness": 2.0, "VALIDITY": 1.0},
    )
    run = client.post(
        "/api/v1/runs",
        headers=tenant.creator,
        json={"snapshot_id": snapshot_id, "ruleset_id": ruleset_id, "policy_id": policy_id, "idempotency_key": uuid4().hex},
    )
    assert run.status_code == 202, run.text

    with db_conn.cursor() as cur:
        cur.execute("SELECT outlier_config->'_run_spec'->'policy' FROM evaluation_runs WHERE run_id = %s;", (run.json()["run_id"],))
        policy = cur.fetchone()[0]
    assert policy["warn_min"] == 10.0
    assert policy["pass_min"] == 20.0
    assert policy["publication_threshold"] == 0.5
    assert policy["critical_acceptance_threshold"] == 95.0
    assert policy["dimension_weights"] == {"COMPLETENESS": 2.0, "VALIDITY": 1.0}


def test_legacy_snapshot_creation_endpoint_is_removed(client: TestClient, tenant: Tenant) -> None:
    """Legacy POST /snapshots creation route is removed; imports route is required."""
    resp = client.post(
        "/api/v1/snapshots",
        headers=tenant.creator,
        json={"asset_id": str(uuid4()), "source_kind": "LOCAL_FILE"},
    )
    assert resp.status_code in (404, 405)

def test_snapshot_records_real_content_hash(client: TestClient, tenant: Tenant, db_conn) -> None:
    """H7: content_sha256 is the SHA-256 of the registered file, not of generated IDs."""
    import hashlib

    _, snapshot_id = _snapshot(client, tenant)
    with db_conn.cursor() as cur:
        cur.execute("SELECT content_sha256 FROM dataset_snapshots WHERE snapshot_id = %s;", (snapshot_id,))
        stored = cur.fetchone()[0]
    assert stored == hashlib.sha256(FIXTURE_CSV.read_bytes()).hexdigest()


def _login_tokens(client: TestClient, email: str, tenant_id: UUID, password: str = PASSWORD) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_id": str(tenant_id)})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def steward(tenant: Tenant, db_conn) -> tuple[str, UUID]:
    """Email and user id of the tenant's DATA_STEWARD approver."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT u.email, u.user_id FROM users u JOIN tenant_memberships m ON m.user_id = u.user_id "
            "WHERE m.tenant_id = %s AND m.role = 'DATA_STEWARD';",
            (tenant.tenant_id,),
        )
        email, user_id = cur.fetchone()
    return email, user_id


def test_refresh_keeps_the_membership_role(client: TestClient, tenant: Tenant, steward) -> None:
    """C4: a refreshed DATA_STEWARD can still approve (refresh used to reset the role)."""
    asset_id, _ = _snapshot(client, tenant)
    rs = client.post(
        "/api/v1/rulesets",
        headers=tenant.creator,
        json={"asset_id": asset_id, "name": "rs", "rules": [{"rule_code": "R", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "id"}}]},
    ).json()["ruleset_id"]
    client.post(f"/api/v1/rulesets/{rs}/submit", headers=tenant.creator, json={})

    tokens = _login_tokens(client, steward[0], tenant.tenant_id)
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    assert client.post(f"/api/v1/rulesets/{rs}/approve", headers=headers, json={}).status_code == 200


def test_refresh_tokens_are_persisted_as_hashes(client: TestClient, tenant: Tenant, steward, db_conn) -> None:
    """Refresh tokens survive API restarts / multiple workers and are never stored in clear."""
    import hashlib

    raw = _login_tokens(client, steward[0], tenant.tenant_id)["refresh_token"]
    with db_conn.cursor() as cur:
        cur.execute("SELECT token_hash, user_id FROM refresh_tokens WHERE user_id = %s;", (steward[1],))
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM refresh_tokens WHERE token_hash = %s;", (raw,))
        raw_matches = cur.fetchone()[0]
    assert (hashlib.sha256(raw.encode()).hexdigest(), steward[1]) in rows
    assert raw_matches == 0


def test_refresh_token_reuse_revokes_the_family(client: TestClient, tenant: Tenant, steward) -> None:
    """AC-023 against the real store: replaying a used token revokes its successors too."""
    t1 = _login_tokens(client, steward[0], tenant.tenant_id)["refresh_token"]
    t2 = client.post("/api/v1/auth/refresh", json={"refresh_token": t1}).json()["refresh_token"]
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": t1})
    assert replay.status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t2}).status_code == 401


def test_refresh_is_rejected_after_membership_is_revoked(client: TestClient, tenant: Tenant, steward, db_conn) -> None:
    token = _login_tokens(client, steward[0], tenant.tenant_id)["refresh_token"]
    with db_conn.cursor() as cur:
        cur.execute("UPDATE tenant_memberships SET status = 'SUSPENDED' WHERE user_id = %s;", (steward[1],))
        db_conn.commit()
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_logout_revokes_the_refresh_token(client: TestClient, tenant: Tenant, steward) -> None:
    token = _login_tokens(client, steward[0], tenant.tenant_id)["refresh_token"]
    assert client.post("/api/v1/auth/logout", json={"refresh_token": token}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_login_does_not_reveal_deactivated_accounts(client: TestClient, tenant: Tenant, steward, db_conn) -> None:
    """H9: a deactivated account with a wrong password looks exactly like an unknown email."""
    with db_conn.cursor() as cur:
        cur.execute("UPDATE users SET is_active = FALSE WHERE user_id = %s;", (steward[1],))
        db_conn.commit()
    deactivated = client.post("/api/v1/auth/login", json={"email": steward[0], "password": "wrong-password"})
    unknown = client.post("/api/v1/auth/login", json={"email": f"nobody_{uuid4().hex[:6]}@example.com", "password": "wrong-password"})
    assert deactivated.status_code == unknown.status_code == 401
    assert deactivated.json()["detail"] == unknown.json()["detail"]


def test_duplicate_asset_name_is_a_conflict_not_a_server_error(client: TestClient, tenant: Tenant) -> None:
    """H8: unique-constraint violations answer 409 without SQL details."""
    name = f"asset_{uuid4().hex[:8]}"
    assert client.post("/api/v1/assets", headers=tenant.creator, json={"name": name}).status_code == 201
    dup = client.post("/api/v1/assets", headers=tenant.creator, json={"name": name})
    assert dup.status_code == 409
    assert "uq_" not in dup.text


def test_approving_a_new_policy_supersedes_the_active_one(client: TestClient, tenant: Tenant, db_conn) -> None:
    """H8: a tenant has one ACTIVE policy; approving another deprecates the old one instead of a 500."""
    first = _active_policy(client, tenant)
    second = _active_policy(client, tenant)
    with db_conn.cursor() as cur:
        cur.execute("SELECT policy_id::text, status FROM scoring_policies WHERE policy_id IN (%s, %s);", (first, second))
        statuses = dict(cur.fetchall())
    assert statuses == {first: "DEPRECATED", second: "ACTIVE"}


def test_concurrent_triggers_with_one_idempotency_key_create_one_run(client: TestClient, tenant: Tenant, db_conn) -> None:
    """H8: simultaneous retries with the same key must all resolve to a single run."""
    import threading

    asset_id, snapshot_id = _snapshot(client, tenant)
    body = {
        "snapshot_id": snapshot_id,
        "ruleset_id": _active_ruleset(client, tenant, asset_id),
        "policy_id": _active_policy(client, tenant),
        "idempotency_key": uuid4().hex,
    }
    barrier = threading.Barrier(8)
    results: list[tuple[int, str]] = []

    def trigger() -> None:
        barrier.wait()
        resp = client.post("/api/v1/runs", headers=tenant.creator, json=body)
        results.append((resp.status_code, resp.json().get("run_id", resp.text)))

    threads = [threading.Thread(target=trigger) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert {code for code, _ in results} == {202}, results
    assert len({run_id for _, run_id in results}) == 1
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM evaluation_runs WHERE idempotency_key = %s;", (body["idempotency_key"],))
        assert cur.fetchone()[0] == 1


def test_scorecard_reports_stored_weighted_coverage_and_advisory_rows(client: TestClient, tenant: Tenant, pg_dsn: str, db_conn) -> None:
    """H2 + H5: outlier advisories load (null rule_id) and coverage is the weighted domain value."""
    from dq_scoring.adapters.compute.in_memory_compute import InMemoryComputeAdapter
    from dq_scoring.adapters.db.postgres_assessment_store import (
        PostgresAssessmentStoreAdapter,
    )
    from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
    from dq_scoring.core.entities import RuleExecutionOutput
    from dq_scoring.core.models import MeasurementStatus, RuleCounts
    from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
    from dq_scoring.workers.evaluation_worker import EvaluationWorker

    asset_id, snapshot_id = _snapshot(client, tenant)
    rules = [
        {"rule_code": "C_HEAVY", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "id"}, "contribution_weight": 3.0},
        {"rule_code": "C_LIGHT", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "amount"}, "contribution_weight": 1.0},
    ]
    rs = client.post("/api/v1/rulesets", headers=tenant.creator, json={"asset_id": asset_id, "name": "cov", "rules": rules}).json()["ruleset_id"]
    client.post(f"/api/v1/rulesets/{rs}/submit", headers=tenant.creator, json={})
    assert client.post(f"/api/v1/rulesets/{rs}/approve", headers=tenant.approver, json={}).status_code == 200
    run = client.post(
        "/api/v1/runs",
        headers=tenant.creator,
        json={"snapshot_id": snapshot_id, "ruleset_id": rs, "policy_id": _active_policy(client, tenant, min_coverage_threshold=0.5), "outlier_columns": ["amount"], "idempotency_key": uuid4().hex},
    ).json()

    with db_conn.cursor() as cur:
        cur.execute("SELECT rule_id FROM quality_rules WHERE ruleset_id = %s AND rule_name = 'C_LIGHT';", (rs,))
        light_rule_id = cur.fetchone()[0]
        cur.execute(
            """
            SELECT asset_id, source_kind, source_descriptor, schema_definition, total_rows, total_columns, captured_at
            FROM dataset_snapshots WHERE snapshot_id = %s;
            """,
            (UUID(snapshot_id),),
        )
        s_row = cur.fetchone()
        snap_entity = DatasetSnapshot(
            snapshot_id=UUID(snapshot_id),
            tenant_id=tenant.tenant_id,
            asset_id=s_row[0],
            source_kind=s_row[1],
            source_descriptor=s_row[2] or {},
            schema_definition=s_row[3] or {},
            total_rows=s_row[4],
            total_columns=s_row[5],
            captured_at=s_row[6],
        )
    compute = InMemoryComputeAdapter()
    compute.register_snapshot(snap_entity)
    compute.set_rule_output(light_rule_id, RuleExecutionOutput(rule_id=light_rule_id, counts=RuleCounts(), status=MeasurementStatus.NOT_MEASURABLE))
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    worker = EvaluationWorker(queue, EvaluationOrchestrator(compute, PostgresAssessmentStoreAdapter(dsn=pg_dsn), queue), worker_id="cov-worker")
    assessment = worker.run_by_id(UUID(run["run_id"]))
    assert assessment is not None

    detail = client.get(f"/api/v1/assessments/{assessment.assessment_id}", headers=tenant.creator)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    completeness = next(d for d in body["dimension_results"] if d["dimension"] == "COMPLETENESS")
    assert completeness["coverage_ratio"] == pytest.approx(0.75)
    advisory = [r for r in body["rule_results"] if r["is_advisory"]]
    assert len(advisory) == 1
    assert advisory[0]["rule_id"] is None
    assert advisory[0]["rule_code"] == "OUTLIER_IQR_amount"
    assert advisory[0]["weight"] == 0.0

    public = client.get(f"/api/v1/assessments/{assessment.assessment_id}/public")
    if public.status_code == 200:
        pub_completeness = next(d for d in public.json()["dimensions"] if d["dimension"] == "COMPLETENESS")
        assert pub_completeness["coverage_ratio"] == pytest.approx(0.75)


def _draft_ruleset(client: TestClient, t: Tenant, asset_id: str, name: str) -> str:
    resp = client.post(
        "/api/v1/rulesets",
        headers=t.creator,
        json={"asset_id": asset_id, "name": name, "rules": [{"rule_code": "R", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "id"}}]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == name
    return resp.json()["ruleset_id"]


def test_governance_requires_submission_and_keeps_names(client: TestClient, tenant: Tenant) -> None:
    """H6: DRAFT -> PENDING_APPROVAL -> ACTIVE, with the configured name returned at every step."""
    asset_id, _ = _snapshot(client, tenant)
    rs = _draft_ruleset(client, tenant, asset_id, "Taxi completeness v1")

    early = client.post(f"/api/v1/rulesets/{rs}/approve", headers=tenant.approver, json={})
    assert early.status_code == 400
    assert "submitted" in early.json()["detail"]

    submitted = client.post(f"/api/v1/rulesets/{rs}/submit", headers=tenant.creator, json={})
    assert submitted.status_code == 200
    assert (submitted.json()["status"], submitted.json()["name"]) == ("PENDING_APPROVAL", "Taxi completeness v1")
    assert client.post(f"/api/v1/rulesets/{rs}/submit", headers=tenant.creator, json={}).status_code == 400

    approved = client.post(f"/api/v1/rulesets/{rs}/approve", headers=tenant.approver, json={})
    assert approved.status_code == 200
    assert (approved.json()["status"], approved.json()["name"]) == ("ACTIVE", "Taxi completeness v1")

    pol = client.post("/api/v1/policies", headers=tenant.creator, json={"name": "Strict policy"}).json()
    sub_pol = client.post(f"/api/v1/policies/{pol['policy_id']}/submit", headers=tenant.creator, json={})
    assert (sub_pol.json()["status"], sub_pol.json()["name"]) == ("PENDING_APPROVAL", "Strict policy")


def test_approving_a_new_ruleset_supersedes_the_assets_active_ruleset(client: TestClient, tenant: Tenant, db_conn) -> None:
    asset_id, _ = _snapshot(client, tenant)
    first = _active_ruleset(client, tenant, asset_id)
    second = _active_ruleset(client, tenant, asset_id)
    with db_conn.cursor() as cur:
        cur.execute("SELECT ruleset_id::text, status FROM rulesets WHERE ruleset_id IN (%s, %s);", (first, second))
        assert dict(cur.fetchall()) == {first: "DEPRECATED", second: "ACTIVE"}


def _create_ruleset_with_rule(client: TestClient, t: Tenant, **rule: object) -> object:
    asset = client.post("/api/v1/assets", headers=t.creator, json={"name": f"asset_{uuid4().hex[:8]}"})
    assert asset.status_code == 201, asset.text
    base = {"rule_code": "R", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "id"}}
    return client.post(
        "/api/v1/rulesets",
        headers=t.creator,
        json={"asset_id": asset.json()["asset_id"], "name": "weights", "rules": [{**base, **rule}]},
    )


def _stored_weight(db_conn, ruleset_id: str) -> float:
    with db_conn.cursor() as cur:
        cur.execute("SELECT weight FROM quality_rules WHERE ruleset_id = %s;", (ruleset_id,))
        return cur.fetchone()[0]


def test_negative_rule_weight_is_rejected(client: TestClient, tenant: Tenant) -> None:
    assert _create_ruleset_with_rule(client, tenant, contribution_weight=-1).status_code == 422


def test_zero_weight_rule_is_stored_as_zero(client: TestClient, tenant: Tenant, db_conn) -> None:
    resp = _create_ruleset_with_rule(client, tenant, contribution_weight=0)
    assert resp.status_code == 201, resp.text
    rs = resp.json()["ruleset_id"]
    assert _stored_weight(db_conn, rs) == 0.0
    submitted = client.post(f"/api/v1/rulesets/{rs}/submit", headers=tenant.creator, json={})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["rules"][0]["contribution_weight"] == 0


def test_advisory_rule_is_stored_with_zero_weight(client: TestClient, tenant: Tenant, db_conn) -> None:
    resp = _create_ruleset_with_rule(client, tenant, is_advisory=True, contribution_weight=2.0)
    assert resp.status_code == 201, resp.text
    assert _stored_weight(db_conn, resp.json()["ruleset_id"]) == 0.0
    assert resp.json()["rules"][0]["contribution_weight"] == 0


def test_non_finite_rule_weight_is_rejected(client: TestClient, tenant: Tenant) -> None:
    asset = client.post("/api/v1/assets", headers=tenant.creator, json={"name": f"asset_{uuid4().hex[:8]}"})
    assert asset.status_code == 201, asset.text
    body = (
        f'{{"asset_id": "{asset.json()["asset_id"]}", "name": "weights", "rules": [{{"rule_code": "R", '
        '"dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "id"}, '
        '"contribution_weight": Infinity}]}'
    )
    resp = client.post(
        "/api/v1/rulesets", headers={**tenant.creator, "Content-Type": "application/json"}, content=body
    )
    assert resp.status_code == 422, resp.text
