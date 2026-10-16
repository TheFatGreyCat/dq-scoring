"""Integration tests for 4-Eyes Governance approval workflow and DRAFT configuration rejection (FR-GOV-005, FR-GOV-006, FR-RUN-002, AC-003)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.app import create_app
from dq_scoring.presentation.api.auth import hash_password


@pytest.fixture(scope="module")
def client(pg_dsn: str) -> TestClient:
    """FastAPI TestClient fixture."""
    app = create_app()
    return TestClient(app)


def test_four_eyes_governance_and_draft_rejection(client: TestClient, db_conn):
    """Test full four-eyes approval workflow, role checks, and draft run rejection."""
    tenant_id = uuid4()
    user_creator_id = uuid4()
    user_submitter_id = uuid4()
    user_viewer_id = uuid4()
    user_owner_id = uuid4()

    pwd = "SecretPassword123!"
    pwd_hash = hash_password(pwd)

    # 1. Seed tenant, users, and memberships
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, %s, 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_id, f"org_{tenant_id.hex[:8]}", "Governance Org"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, %s, %s, 'Creator Steward', TRUE),
                   (%s, %s, %s, 'Submitter Steward', TRUE),
                   (%s, %s, %s, 'Business Viewer', TRUE),
                   (%s, %s, %s, 'Data Owner Approver', TRUE);
            """,
            (
                user_creator_id,
                f"creator_{user_creator_id.hex[:8]}@example.com",
                pwd_hash,
                user_submitter_id,
                f"submitter_{user_submitter_id.hex[:8]}@example.com",
                pwd_hash,
                user_viewer_id,
                f"viewer_{user_viewer_id.hex[:8]}@example.com",
                pwd_hash,
                user_owner_id,
                f"owner_{user_owner_id.hex[:8]}@example.com",
                pwd_hash,
            ),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'DATA_STEWARD', 'ACTIVE'),
                   (%s, %s, 'DATA_STEWARD', 'ACTIVE'),
                   (%s, %s, 'BUSINESS_VIEWER', 'ACTIVE'),
                   (%s, %s, 'DATA_OWNER', 'ACTIVE');
            """,
            (
                tenant_id,
                user_creator_id,
                tenant_id,
                user_submitter_id,
                tenant_id,
                user_viewer_id,
                tenant_id,
                user_owner_id,
            ),
        )
        db_conn.commit()

    def get_token(email: str) -> dict[str, str]:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": pwd, "tenant_id": str(tenant_id)},
        )
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    creator_hdr = get_token(f"creator_{user_creator_id.hex[:8]}@example.com")
    submitter_hdr = get_token(f"submitter_{user_submitter_id.hex[:8]}@example.com")
    viewer_hdr = get_token(f"viewer_{user_viewer_id.hex[:8]}@example.com")
    owner_hdr = get_token(f"owner_{user_owner_id.hex[:8]}@example.com")

    # 2. Register asset and snapshot
    asset_resp = client.post(
        "/api/v1/assets",
        headers=creator_hdr,
        json={
            "name": "Governance Test Dataset",
        },
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["asset_id"]

    from tests.support.object_snapshots import register_snapshot_via_api
    snap = register_snapshot_via_api(client, creator_hdr, content_or_path=b"id,fare,trip_distance\n1,12,3\n", asset_id=asset_id)
    snap_id = snap["snapshot_id"]

    # 3. Creator creates DRAFT ruleset
    ruleset_resp = client.post(
        "/api/v1/rulesets",
        headers=creator_hdr,
        json={
            "asset_id": asset_id,
            "name": "Governance Ruleset",
            "rules": [
                {
                    "rule_code": "R_COMP_ID",
                    "dimension": "Completeness",
                    "rule_type": "NON_NULL",
                    "parameters": {"column": "id"},
                    "is_required": True,
                }
            ],
        },
    )
    assert ruleset_resp.status_code == 201
    ruleset_id = ruleset_resp.json()["ruleset_id"]
    assert ruleset_resp.json()["status"] == "DRAFT"

    # 4. Creator creates DRAFT policy
    policy_resp = client.post(
        "/api/v1/policies",
        headers=creator_hdr,
        json={
            "name": "Governance Policy",
            "gate_fail_threshold": 60.0,
            "gate_warn_threshold": 80.0,
            "min_coverage_threshold": 0.80,
            "critical_acceptance_threshold": 95.0,
        },
    )
    assert policy_resp.status_code == 201
    policy_id = policy_resp.json()["policy_id"]
    assert policy_resp.json()["status"] == "DRAFT"

    # 5. FR-GOV-005 & FR-RUN-002: Attempting to trigger run with DRAFT ruleset -> rejected with 422 CONFIGURATION_NOT_APPROVED
    draft_run_resp = client.post(
        "/api/v1/runs",
        headers=creator_hdr,
        json={
            "snapshot_id": snap_id,
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
        },
    )
    assert draft_run_resp.status_code == 422
    assert "CONFIGURATION_NOT_APPROVED" in draft_run_resp.json()["detail"]
    assert "Ruleset" in draft_run_resp.json()["detail"]

    # 6. Submitter submits ruleset
    sub_rs = client.post(
        f"/api/v1/rulesets/{ruleset_id}/submit",
        headers=submitter_hdr,
        json={"notes": "Submitted by steward 2"},
    )
    assert sub_rs.status_code == 200

    # 7. Submitter attempts self-approval -> 403 Forbidden
    sub_appr_rs = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=submitter_hdr,
        json={"approval_notes": "Submitter self-approval"},
    )
    assert sub_appr_rs.status_code == 403
    assert "Independent approval violation" in sub_appr_rs.json()["detail"]

    # 8. Creator attempts to approve draft created by self -> 403 Forbidden
    creator_appr_rs = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=creator_hdr,
        json={"approval_notes": "Creator approval attempt"},
    )
    assert creator_appr_rs.status_code == 403
    assert "Independent approval violation" in creator_appr_rs.json()["detail"]

    # 9. Business Viewer attempts to approve -> 403 Forbidden (role check)
    viewer_appr_rs = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=viewer_hdr,
        json={"approval_notes": "Viewer approval attempt"},
    )
    assert viewer_appr_rs.status_code == 403
    assert "Insufficient permissions" in viewer_appr_rs.json()["detail"]

    # 10. Data Owner (independent) approves ruleset -> 200 OK, becomes ACTIVE
    owner_appr_rs = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=owner_hdr,
        json={"approval_notes": "Approved by Data Owner"},
    )
    assert owner_appr_rs.status_code == 200
    assert owner_appr_rs.json()["status"] == "ACTIVE"

    # 11. Trying to approve already ACTIVE ruleset -> 400 Bad Request
    re_appr_rs = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=owner_hdr,
        json={"approval_notes": "Double approval attempt"},
    )
    assert re_appr_rs.status_code == 400

    # 12. Trigger run now: ruleset is ACTIVE, but policy is still DRAFT -> 422 CONFIGURATION_NOT_APPROVED (Policy)
    draft_pol_run_resp = client.post(
        "/api/v1/runs",
        headers=creator_hdr,
        json={
            "snapshot_id": snap_id,
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
        },
    )
    assert draft_pol_run_resp.status_code == 422
    assert "CONFIGURATION_NOT_APPROVED" in draft_pol_run_resp.json()["detail"]
    assert "Scoring Policy" in draft_pol_run_resp.json()["detail"]

    # 13. Submitter submits policy
    sub_pol = client.post(
        f"/api/v1/policies/{policy_id}/submit",
        headers=submitter_hdr,
        json={"notes": "Policy submitted by steward 2"},
    )
    assert sub_pol.status_code == 200

    # 14. Creator & Submitter self-approval of policy -> 403 Forbidden
    sub_appr_pol = client.post(
        f"/api/v1/policies/{policy_id}/approve",
        headers=submitter_hdr,
        json={"approval_notes": "Submitter self-approval"},
    )
    assert sub_appr_pol.status_code == 403

    creator_appr_pol = client.post(
        f"/api/v1/policies/{policy_id}/approve",
        headers=creator_hdr,
        json={"approval_notes": "Creator self-approval"},
    )
    assert creator_appr_pol.status_code == 403

    # 15. Data Owner approves policy -> 200 OK, becomes ACTIVE
    owner_appr_pol = client.post(
        f"/api/v1/policies/{policy_id}/approve",
        headers=owner_hdr,
        json={"approval_notes": "Policy approved by Data Owner"},
    )
    assert owner_appr_pol.status_code == 200
    assert owner_appr_pol.json()["status"] == "ACTIVE"

    # 16. Trigger run with both ruleset & policy ACTIVE -> 202 Accepted, QUEUED
    success_run_resp = client.post(
        "/api/v1/runs",
        headers=creator_hdr,
        json={
            "snapshot_id": snap_id,
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
            "idempotency_key": f"gov-run-{uuid4()}",
        },
    )
    assert success_run_resp.status_code == 202
    assert success_run_resp.json()["status"] == "QUEUED"

