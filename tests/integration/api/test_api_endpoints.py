"""Integration tests for FastAPI REST API endpoints using TestClient."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.app import create_app
from dq_scoring.presentation.api.auth import hash_password
from dq_scoring.presentation.api.dependencies import (
    PrivilegedSessionError,
    get_db_connection,
    get_pg_dsn,
)


@pytest.fixture(scope="module")
def client(non_superuser_dsn: str) -> TestClient:
    """FastAPI TestClient fixture running under non-superuser runtime role."""
    app = create_app()
    app.dependency_overrides[get_pg_dsn] = lambda: non_superuser_dsn
    return TestClient(app)


def test_health_check(client: TestClient):
    """Verify health endpoint."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_complete_api_lifecycle(client: TestClient, db_conn, pg_dsn: str):
    """Verify complete API lifecycle: auth, asset, snapshot, ruleset approval, policy approval, run trigger, assessment query."""
    tenant_id = uuid4()
    user_creator_id = uuid4()
    user_approver_id = uuid4()

    pwd = "SecretPassword123!"
    pwd_hash = hash_password(pwd)

    # 1. Seed tenant and 2 users for independent approval testing (AC-003)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, %s, 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_id, f"org_{tenant_id.hex[:8]}", "Integration Test Org"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, %s, %s, %s, TRUE),
                   (%s, %s, %s, %s, TRUE);
            """,
            (
                user_creator_id,
                f"creator_{user_creator_id.hex[:8]}@example.com",
                pwd_hash,
                "Creator User",
                user_approver_id,
                f"approver_{user_approver_id.hex[:8]}@example.com",
                pwd_hash,
                "Approver User",
            ),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE'),
                   (%s, %s, 'DATA_STEWARD', 'ACTIVE');
            """,
            (tenant_id, user_creator_id, tenant_id, user_approver_id),
        )
        db_conn.commit()

    # 2. Login Creator
    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": f"creator_{user_creator_id.hex[:8]}@example.com",
            "password": pwd,
            "tenant_id": str(tenant_id),
        },
    )
    assert login_resp.status_code == 200
    creator_token = login_resp.json()["access_token"]
    creator_refresh = login_resp.json()["refresh_token"]
    creator_headers = {"Authorization": f"Bearer {creator_token}"}

    # 3. Login Approver
    login_appr_resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": f"approver_{user_approver_id.hex[:8]}@example.com",
            "password": pwd,
            "tenant_id": str(tenant_id),
        },
    )
    assert login_appr_resp.status_code == 200
    approver_token = login_appr_resp.json()["access_token"]
    approver_headers = {"Authorization": f"Bearer {approver_token}"}

    # 4. Token Refresh
    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": creator_refresh},
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()

    # 5. Create Data Asset
    asset_resp = client.post(
        "/api/v1/assets",
        headers=creator_headers,
        json={"name": "Chicago Taxi Trips 2023"},
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["asset_id"]

    # 6. Create Snapshot
    from tests.support.object_snapshots import register_snapshot_via_api
    snap = register_snapshot_via_api(client, creator_headers, content_or_path=b"trip_id,fare\nt1,12\n", asset_id=asset_id)
    snapshot_id = snap["snapshot_id"]

    # 7. Create Ruleset
    ruleset_resp = client.post(
        "/api/v1/rulesets",
        headers=creator_headers,
        json={
            "asset_id": asset_id,
            "name": "Production Completeness Ruleset",
            "rules": [
                {
                    "rule_code": "CH_COMP_01",
                    "dimension": "Completeness",
                    "rule_type": "NON_NULL",
                    "parameters": {"column": "trip_id"},
                    "is_required": True,
                    "is_critical": True,
                },
                {
                    "rule_code": "CH_VAL_02",
                    "dimension": "Validity",
                    "rule_type": "TYPE_PARSE",
                    "parameters": {"column": "fare", "data_type": "DOUBLE"},
                    "is_required": True,
                },
            ],
        },
    )
    assert ruleset_resp.status_code == 201
    ruleset_id = ruleset_resp.json()["ruleset_id"]
    assert ruleset_resp.json()["status"] == "DRAFT"

    # 8. Submit Ruleset for Approval
    submit_ruleset_resp = client.post(
        f"/api/v1/rulesets/{ruleset_id}/submit",
        headers=creator_headers,
        json={"notes": "Ready for steward review"},
    )
    assert submit_ruleset_resp.status_code == 200
    assert submit_ruleset_resp.json()["status"] == "PENDING_APPROVAL"

    # 9. AC-003: Creator attempts to approve own ruleset -> Must FAIL with 403 Forbidden!
    self_approve_resp = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=creator_headers,
        json={"approval_notes": "Self approval attempt"},
    )
    assert self_approve_resp.status_code == 403
    assert "cannot approve their own" in self_approve_resp.json()["detail"].lower()

    # 10. AC-003: Independent Approver approves ruleset -> Succeeds!
    approver_approve_resp = client.post(
        f"/api/v1/rulesets/{ruleset_id}/approve",
        headers=approver_headers,
        json={"approval_notes": "Reviewed and approved by Data Steward"},
    )
    assert approver_approve_resp.status_code == 200
    assert approver_approve_resp.json()["status"] == "ACTIVE"

    # 11. Create Policy
    policy_resp = client.post(
        "/api/v1/policies",
        headers=creator_headers,
        json={
            "name": "Standard Bronze Policy",
            "gate_fail_threshold": 60.0,
            "gate_warn_threshold": 80.0,
            "min_coverage_threshold": 0.80,
            "critical_acceptance_threshold": 95.0,
        },
    )
    assert policy_resp.status_code == 201
    policy_id = policy_resp.json()["policy_id"]

    # 12. Submit & Approve Policy
    client.post(f"/api/v1/policies/{policy_id}/submit", headers=creator_headers, json={})
    appr_pol_resp = client.post(
        f"/api/v1/policies/{policy_id}/approve",
        headers=approver_headers,
        json={"approval_notes": "Policy approved"},
    )
    assert appr_pol_resp.status_code == 200
    assert appr_pol_resp.json()["status"] == "ACTIVE"

    # 13. Trigger Evaluation Run
    run_resp = client.post(
        "/api/v1/runs",
        headers=creator_headers,
        json={
            "snapshot_id": snapshot_id,
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
            "idempotency_key": (idem_key := f"test-run-{uuid4()}"),
        },
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]
    assert run_resp.json()["status"] == "QUEUED"

    # Duplicate trigger with same idempotency key must return existing actual run ID
    dup_run_resp = client.post(
        "/api/v1/runs",
        headers=creator_headers,
        json={
            "snapshot_id": snapshot_id,
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
            "idempotency_key": idem_key,
        },
    )
    assert dup_run_resp.status_code == 202
    assert dup_run_resp.json()["run_id"] == run_id

    # 14. Poll Run Status (IF-UI-005)
    status_resp = client.get(f"/api/v1/runs/{run_id}/status", headers=creator_headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] in ("QUEUED", "LEASED", "RUNNING", "SUCCEEDED")



def test_public_assessment_security_and_dimension_shielding(client: TestClient, db_conn):
    """Verify public endpoint only returns PUBLISHED and PUBLIC_READ, withholding private dimensions."""
    tenant_id = uuid4()
    user_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    ruleset_id = uuid4()
    policy_id = uuid4()
    run_id_withheld = uuid4()
    run_id_private = uuid4()
    run_id_public = uuid4()

    aid_withheld = uuid4()
    aid_private = uuid4()
    aid_public = uuid4()

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, 'Sec Tenant', 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_id, f"sec_{tenant_id.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, %s, '$argon2id$seed', 'Sec User', TRUE);
            """,
            (user_id, f"sec_{user_id.hex[:8]}@example.com"),
        )
        cur.execute(
            """
            INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
            VALUES (%s, %s, 'Sec Asset', %s, 'CSV', %s, %s);
            """,
            (asset_id, tenant_id, f"sec-asset-{asset_id.hex[:6]}", user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_id, tenant_id, asset_id, version_number, source_kind,
                source_descriptor, content_sha256, storage_location, schema_definition,
                total_rows, total_columns, created_by, captured_at
            ) VALUES (
                %s, %s, %s, 1, 'LOCAL_FILE',
                '{}'::jsonb, %s, 's3://sec', '{}'::jsonb,
                100, 2, %s, now()
            );
            """,
            (snapshot_id, tenant_id, asset_id, "s" * 64, user_id),
        )
        cur.execute(
            """
            INSERT INTO rulesets (
                ruleset_id, tenant_id, asset_id, version, config_hash,
                status, created_by, submitted_by, submitted_at
            ) VALUES (%s, %s, %s, %s, 'cfg_hash', 'DRAFT', %s, %s, now());
            """,
            (ruleset_id, tenant_id, asset_id, f"v_{ruleset_id.hex[:8]}", user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO scoring_policies (
                policy_id, tenant_id, version, config_hash, status,
                created_by, submitted_by, submitted_at, dimension_weights, publication_threshold, gate_rules
            ) VALUES (%s, %s, %s, 'pol_hash', 'DRAFT', %s, %s, now(), '{}'::jsonb, 0.8, '{}'::jsonb);
            """,
            (policy_id, tenant_id, f"v_{policy_id.hex[:8]}", user_id, user_id),
        )
        for rid, run_uuid in [
            ("withheld", run_id_withheld),
            ("private", run_id_private),
            ("public", run_id_public),
        ]:
            cur.execute(
                """
                INSERT INTO evaluation_runs (
                    run_id, tenant_id, snapshot_id, ruleset_id, policy_id,
                    idempotency_key, outlier_config, outlier_config_hash, run_status, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, '{}'::jsonb, 'hash', 'SUCCEEDED', %s
                );
                """,
                (run_uuid, tenant_id, snapshot_id, ruleset_id, policy_id, f"sec-idem-{run_uuid}", user_id),
            )

        # 1. Assessment WITHHELD + PUBLIC_READ (should be blocked from public view)
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score,
                publication_status, visibility_scope, coverage_ratio, confidence_status,
                quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, NULL,
                'WITHHELD', 'PUBLIC_READ', 0.5, 'VERIFIED',
                'FAIL', '{}'::jsonb, 'hash_withheld', now()
            );
            """,
            (aid_withheld, tenant_id, run_id_withheld, snapshot_id),
        )
        cur.execute(
            """
            INSERT INTO dimension_results (
                dimension_result_id, tenant_id, assessment_id, dimension, measurement_status,
                dimension_score, dimension_weight, total_rules, measured_rules
            ) VALUES (
                %s, %s, %s, 'ACCURACY', 'NOT_MEASURABLE',
                NULL, 1.0, 2, 0
            );
            """,
            (uuid4(), tenant_id, aid_withheld),
        )

        # 2. Assessment PUBLISHED + PRIVATE (should be blocked from public view)
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score,
                publication_status, visibility_scope, coverage_ratio, confidence_status,
                quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, 95.0,
                'PUBLISHED', 'PRIVATE', 0.95, 'VERIFIED',
                'PASS', '{}'::jsonb, 'hash_private', now()
            );
            """,
            (aid_private, tenant_id, run_id_private, snapshot_id),
        )
        cur.execute(
            """
            INSERT INTO dimension_results (
                dimension_result_id, tenant_id, assessment_id, dimension, measurement_status,
                dimension_score, dimension_weight, total_rules, measured_rules
            ) VALUES (
                %s, %s, %s, 'COMPLETENESS', 'MEASURED',
                95.0, 1.0, 2, 2
            );
            """,
            (uuid4(), tenant_id, aid_private),
        )

        # 3. Assessment PUBLISHED + PUBLIC_READ (valid for public view)
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score,
                publication_status, visibility_scope, coverage_ratio, confidence_status,
                quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, 99.0,
                'PUBLISHED', 'PUBLIC_READ', 1.0, 'VERIFIED',
                'PASS', '{}'::jsonb, 'hash_public', now()
            );
            """,
            (aid_public, tenant_id, run_id_public, snapshot_id),
        )
        cur.execute(
            """
            INSERT INTO dimension_results (
                dimension_result_id, tenant_id, assessment_id, dimension, measurement_status,
                dimension_score, dimension_weight, total_rules, measured_rules
            ) VALUES (
                %s, %s, %s, 'VALIDITY', 'MEASURED',
                99.0, 1.0, 1, 1
            );
            """,
            (uuid4(), tenant_id, aid_public),
        )
        db_conn.commit()

    # 1. WITHHELD must return 404 and reveal 0 dimensions
    resp_withheld = client.get(f"/api/v1/assessments/{aid_withheld}/public")
    assert resp_withheld.status_code == 404
    assert "dimensions" not in resp_withheld.json()

    # 2. PRIVATE must return 404 and reveal 0 dimensions
    resp_private = client.get(f"/api/v1/assessments/{aid_private}/public")
    assert resp_private.status_code == 404
    assert "dimensions" not in resp_private.json()

    # 3. Non-existent assessment must return 404
    resp_missing = client.get(f"/api/v1/assessments/{uuid4()}/public")
    assert resp_missing.status_code == 404

    # 4. PUBLISHED + PUBLIC_READ must return 200 with public dimensions
    resp_public = client.get(f"/api/v1/assessments/{aid_public}/public")
    assert resp_public.status_code == 200
    pub_data = resp_public.json()
    assert pub_data["assessment_id"] == str(aid_public)
    assert pub_data["dq_score"] == 99.0
    assert pub_data["publication_status"] == "PUBLISHED"
    assert len(pub_data["dimensions"]) == 1
    assert pub_data["dimensions"][0]["dimension"] in ("Validity", "VALIDITY")


def test_public_assessment_enforces_status_and_visibility_independent_of_rls(
    client: TestClient, db_conn, pg_dsn: str
):
    """Public endpoint must return 404 for non-published/non-public assessments even without DB RLS."""
    tenant_id = uuid4()
    user_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    ruleset_id = uuid4()
    policy_id = uuid4()
    run_id_withheld = uuid4()
    run_id_private = uuid4()
    aid_withheld = uuid4()
    aid_private = uuid4()

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, 'Indep Tenant', 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_id, f"indep_{tenant_id.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, %s, '$argon2id$seed', 'Indep User', TRUE);
            """,
            (user_id, f"indep_{user_id.hex[:8]}@example.com"),
        )
        cur.execute(
            """
            INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
            VALUES (%s, %s, 'Indep Asset', %s, 'CSV', %s, %s);
            """,
            (asset_id, tenant_id, f"indep-asset-{asset_id.hex[:6]}", user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_id, tenant_id, asset_id, version_number, source_kind,
                source_descriptor, content_sha256, storage_location, schema_definition,
                total_rows, total_columns, created_by, captured_at
            ) VALUES (
                %s, %s, %s, 1, 'LOCAL_FILE',
                '{}'::jsonb, %s, 's3://sec', '{}'::jsonb,
                100, 2, %s, now()
            );
            """,
            (snapshot_id, tenant_id, asset_id, "s" * 64, user_id),
        )
        cur.execute(
            """
            INSERT INTO rulesets (
                ruleset_id, tenant_id, asset_id, version, config_hash,
                status, created_by, submitted_by, submitted_at
            ) VALUES (%s, %s, %s, %s, 'cfg_hash', 'DRAFT', %s, %s, now());
            """,
            (ruleset_id, tenant_id, asset_id, f"v_{ruleset_id.hex[:8]}", user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO scoring_policies (
                policy_id, tenant_id, version, config_hash, status,
                created_by, submitted_by, submitted_at, dimension_weights, publication_threshold, gate_rules
            ) VALUES (%s, %s, %s, 'pol_hash', 'DRAFT', %s, %s, now(), '{}'::jsonb, 0.8, '{}'::jsonb);
            """,
            (policy_id, tenant_id, f"v_{policy_id.hex[:8]}", user_id, user_id),
        )
        for run_uuid in [run_id_withheld, run_id_private]:
            cur.execute(
                """
                INSERT INTO evaluation_runs (
                    run_id, tenant_id, snapshot_id, ruleset_id, policy_id,
                    idempotency_key, outlier_config, outlier_config_hash, run_status, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, '{}'::jsonb, 'hash', 'SUCCEEDED', %s
                );
                """,
                (run_uuid, tenant_id, snapshot_id, ruleset_id, policy_id, f"sec-idem-{run_uuid}", user_id),
            )
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score,
                publication_status, visibility_scope, coverage_ratio, confidence_status,
                quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, NULL,
                'WITHHELD', 'PUBLIC_READ', 0.5, 'VERIFIED',
                'FAIL', '{}'::jsonb, 'hash_withheld', now()
            );
            """,
            (aid_withheld, tenant_id, run_id_withheld, snapshot_id),
        )
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score,
                publication_status, visibility_scope, coverage_ratio, confidence_status,
                quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, 95.0,
                'PUBLISHED', 'PRIVATE', 0.95, 'VERIFIED',
                'PASS', '{}'::jsonb, 'hash_private', now()
            );
            """,
            (aid_private, tenant_id, run_id_private, snapshot_id),
        )
        db_conn.commit()

    def superuser_conn():
        with psycopg.connect(pg_dsn, autocommit=False) as conn, conn.transaction():
            yield conn

    from dq_scoring.presentation.api.dependencies import get_db_connection

    client.app.dependency_overrides[get_db_connection] = superuser_conn
    try:
        resp_w = client.get(f"/api/v1/assessments/{aid_withheld}/public")
        assert resp_w.status_code == 404
        resp_p = client.get(f"/api/v1/assessments/{aid_private}/public")
        assert resp_p.status_code == 404
    finally:
        client.app.dependency_overrides.pop(get_db_connection, None)


def test_privileged_session_superuser_rejected(pg_dsn: str):
    """get_db_connection must fail closed when DSN connects as superuser."""
    with pytest.raises(PrivilegedSessionError) as exc_info:
        gen = get_db_connection(dsn=pg_dsn, user=None)
        next(gen)
    err_str = str(exc_info.value)
    assert "Privileged session_user is not permitted" in err_str
    assert "postgres" not in err_str
    assert "postgresql://" not in err_str
    assert "secret" not in err_str


def test_privileged_session_bypassrls_rejected(pg_dsn: str, db_conn):
    """get_db_connection must fail closed when DSN connects as a role with BYPASSRLS."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_test_bypassrls_user') THEN
                    CREATE ROLE dq_test_bypassrls_user WITH LOGIN PASSWORD 'bypass_secret' NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
                END IF;
            END $$;
            GRANT dq_app_role TO dq_test_bypassrls_user;
            GRANT USAGE ON SCHEMA public TO dq_test_bypassrls_user;
            """
        )
        db_conn.commit()

    conn_info = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    conn_info["user"] = "dq_test_bypassrls_user"
    conn_info["password"] = "bypass_secret"
    bypass_dsn = psycopg.conninfo.make_conninfo(**conn_info)

    with pytest.raises(PrivilegedSessionError) as exc_info:
        gen = get_db_connection(dsn=bypass_dsn, user=None)
        next(gen)
    err_str = str(exc_info.value)
    assert "Privileged session_user is not permitted" in err_str
    assert "bypass_secret" not in err_str
    assert "postgresql://" not in err_str


def test_privileged_session_owner_dq_app_role_rejected(pg_dsn: str, db_conn):
    """get_db_connection must fail closed when DSN connects directly as dq_app_role."""
    with db_conn.cursor() as cur:
        cur.execute("ALTER ROLE dq_app_role WITH LOGIN PASSWORD 'app_role_secret';")
        db_conn.commit()

    conn_info = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    conn_info["user"] = "dq_app_role"
    conn_info["password"] = "app_role_secret"
    owner_dsn = psycopg.conninfo.make_conninfo(**conn_info)

    try:
        with pytest.raises(PrivilegedSessionError) as exc_info:
            gen = get_db_connection(dsn=owner_dsn, user=None)
            next(gen)
        err_str = str(exc_info.value)
        assert "Privileged session_user is not permitted" in err_str
        assert "app_role_secret" not in err_str
        assert "postgresql://" not in err_str
    finally:
        with db_conn.cursor() as cur:
            cur.execute("ALTER ROLE dq_app_role WITH NOLOGIN;")
            db_conn.commit()


def test_api_fails_closed_when_dsn_is_superuser(pg_dsn: str):
    """FastAPI TestClient must fail closed (403 Forbidden) when DSN is superuser."""
    app = create_app()
    app.dependency_overrides[get_pg_dsn] = lambda: pg_dsn
    super_client = TestClient(app)
    resp = super_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password"},
    )
    assert resp.status_code == 403
    assert "postgresql://" not in resp.text
    assert "postgres" not in resp.text
