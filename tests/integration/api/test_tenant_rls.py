"""Integration tests for PostgreSQL Row Level Security (RLS) enforcement in API."""

from __future__ import annotations

from contextlib import closing
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.app import create_app
from dq_scoring.presentation.api.auth import AuthenticatedUser, hash_password
from dq_scoring.presentation.api.dependencies import get_db_connection, get_pg_dsn


@pytest.fixture
def non_superuser_dsn(pg_dsn: str, db_conn) -> str:
    """Ensure non-superuser runtime role exists and return DSN using it."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_app_user') THEN
                    CREATE ROLE dq_app_user WITH LOGIN PASSWORD 'dq_app_user_secret' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END $$;
            GRANT dq_app_role TO dq_app_user;
            GRANT USAGE ON SCHEMA public TO dq_app_user;
            """
        )
        db_conn.commit()

    conn_info = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    conn_info["user"] = "dq_app_user"
    conn_info["password"] = "dq_app_user_secret"
    return psycopg.conninfo.make_conninfo(**conn_info)


@pytest.fixture
def client(non_superuser_dsn: str) -> TestClient:
    """FastAPI TestClient fixture running under non-superuser runtime role."""
    app = create_app()
    app.dependency_overrides[get_pg_dsn] = lambda: non_superuser_dsn
    return TestClient(app)


def test_login_under_dq_app_role_with_single_and_multi_tenant_membership(
    client: TestClient, db_conn
) -> None:
    """Verify login authenticates without superuser or RLS bypass and resolves membership."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_1_id = uuid4()
    user_2_id = uuid4()

    pwd = "SecurePassword123!"
    pwd_hash = hash_password(pwd)

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, 'Tenant Alpha', 'ENTERPRISE', 'ACTIVE'),
                   (%s, %s, 'Tenant Beta', 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_a, f"alpha_{tenant_a.hex[:6]}", tenant_b, f"beta_{tenant_b.hex[:6]}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, 'u1@example.com', %s, 'User One', TRUE),
                   (%s, 'u2@example.com', %s, 'User Two', TRUE);
            """,
            (user_1_id, pwd_hash, user_2_id, pwd_hash),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE'),
                   (%s, %s, 'DATA_STEWARD', 'ACTIVE'),
                   (%s, %s, 'BUSINESS_VIEWER', 'ACTIVE');
            """,
            (tenant_a, user_1_id, tenant_b, user_1_id, tenant_b, user_2_id),
        )
        db_conn.commit()

    # 1. User 1 logs in without specifying tenant -> resolves active membership
    resp1 = client.post(
        "/api/v1/auth/login",
        json={"email": "u1@example.com", "password": pwd},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert "access_token" in data1

    # 2. User 1 logs in specifying Tenant B explicitly -> resolves Tenant B
    resp2 = client.post(
        "/api/v1/auth/login",
        json={"email": "u1@example.com", "password": pwd, "tenant_id": str(tenant_b)},
    )
    assert resp2.status_code == 200

    # 3. User 1 invalid password -> 401
    resp3 = client.post(
        "/api/v1/auth/login",
        json={"email": "u1@example.com", "password": "WrongPassword!"},
    )
    assert resp3.status_code == 401

    # 4. User 2 requests Tenant A (not a member) -> 403 Forbidden
    resp4 = client.post(
        "/api/v1/auth/login",
        json={"email": "u2@example.com", "password": pwd, "tenant_id": str(tenant_a)},
    )
    assert resp4.status_code == 403

    # 5. Non-existent email -> 401
    resp5 = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": pwd},
    )
    assert resp5.status_code == 401


def test_authenticated_cross_tenant_isolation_under_rls(
    client: TestClient, db_conn
) -> None:
    """Verify authenticated API accesses enforce row-level security per token tenant."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a_id = uuid4()
    user_b_id = uuid4()

    pwd = "SecurePassword123!"
    pwd_hash = hash_password(pwd)

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, 'Tenant A', 'ENTERPRISE', 'ACTIVE'),
                   (%s, %s, 'Tenant B', 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_a, f"ta_{tenant_a.hex[:6]}", tenant_b, f"tb_{tenant_b.hex[:6]}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, 'usera@example.com', %s, 'User A', TRUE),
                   (%s, 'userb@example.com', %s, 'User B', TRUE);
            """,
            (user_a_id, pwd_hash, user_b_id, pwd_hash),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'WORKSPACE_ADMIN', 'ACTIVE'),
                   (%s, %s, 'WORKSPACE_ADMIN', 'ACTIVE');
            """,
            (tenant_a, user_a_id, tenant_b, user_b_id),
        )
        db_conn.commit()

    # Login User A in Tenant A
    login_a = client.post(
        "/api/v1/auth/login",
        json={"email": "usera@example.com", "password": pwd, "tenant_id": str(tenant_a)},
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Login User B in Tenant B
    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": "userb@example.com", "password": pwd, "tenant_id": str(tenant_b)},
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates Asset in Tenant A
    resp_asset_a = client.post(
        "/api/v1/assets",
        headers=headers_a,
        json={"name": "Alpha Asset"},
    )
    assert resp_asset_a.status_code == 201
    asset_a_id = resp_asset_a.json()["asset_id"]

    # User A creates Snapshot in Tenant A referencing Asset A
    from tests.support.object_snapshots import register_snapshot_via_api
    snap = register_snapshot_via_api(client, headers_a, content_or_path=b"col1,col2\na,b\n", asset_id=asset_a_id)
    snap_a_id = snap["snapshot_id"]

    # User B attempts to create a snapshot referencing Tenant A's asset_a_id
    # Under Tenant B's RLS session, asset_a_id does not exist -> 404
    resp_cross_create = client.post(
        "/api/v1/imports",
        headers=headers_b,
        json={
            "asset_id": asset_a_id,
            "client_request_id": str(uuid4()),
            "format": "CSV", "original_filename": "test.csv", "size_bytes": 10,
        },
    )
    assert resp_cross_create.status_code == 404

    # User B attempts to retrieve Tenant A's snapshot -> 404 Not Found (invisible via RLS)
    resp_cross_get = client.get(
        f"/api/v1/snapshots/{snap_a_id}",
        headers=headers_b,
    )
    assert resp_cross_get.status_code == 404

    # User A successfully retrieves own snapshot
    resp_own_get = client.get(
        f"/api/v1/snapshots/{snap_a_id}",
        headers=headers_a,
    )
    assert resp_own_get.status_code == 200
    assert resp_own_get.json()["snapshot_id"] == snap_a_id


def test_public_assessment_rls_filtering(
    client: TestClient, db_conn, non_superuser_dsn: str
) -> None:
    """Verify unauthenticated public endpoint reads published public assessments only."""
    tenant_id = uuid4()
    user_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    ruleset_id = uuid4()
    policy_id = uuid4()
    run_1_id = uuid4()
    run_2_id = uuid4()
    run_3_id = uuid4()
    assessment_pub_id = uuid4()
    assessment_priv_id = uuid4()
    assessment_restricted_id = assessment_priv_id
    assessment_withheld_id = uuid4()
    assessment_draft_id = assessment_withheld_id
    dim_id = uuid4()

    pwd = "SecurePassword123!"
    pwd_hash = hash_password(pwd)

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, 'Public Test Org', 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_id, f"org_{tenant_id.hex[:6]}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, 'admin@example.com', %s, 'Admin User', TRUE);
            """,
            (user_id, pwd_hash),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'WORKSPACE_ADMIN', 'ACTIVE');
            """,
            (tenant_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
            VALUES (%s, %s, 'Asset 1', 'asset-1', 'CSV', %s, %s);
            """,
            (asset_id, tenant_id, user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_id, tenant_id, asset_id, version_number, source_kind, source_descriptor,
                content_sha256, storage_location, schema_definition, total_rows, total_columns,
                created_by, captured_at
            ) VALUES (
                %s, %s, %s, 1, 'LOCAL_FILE', '{}'::jsonb,
                repeat('a', 64), 's3://bucket/path', '{}'::jsonb, 100, 2, %s, now()
            );
            """,
            (snapshot_id, tenant_id, asset_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO rulesets (
                ruleset_id, tenant_id, asset_id, version, config_hash, status,
                created_by, submitted_by, submitted_at, approved_by, approved_at
            ) VALUES (
                %s, %s, %s, '1.0.0', repeat('r', 64), 'ACTIVE',
                %s, %s, now(), %s, now()
            );
            """,
            (ruleset_id, tenant_id, asset_id, user_id, user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO scoring_policies (
                policy_id, tenant_id, version, config_hash, status, dimension_weights, gate_rules,
                created_by, submitted_by, submitted_at, approved_by, approved_at
            ) VALUES (
                %s, %s, '1.0.0', repeat('p', 64), 'ACTIVE', '{}'::jsonb, '{}'::jsonb,
                %s, %s, now(), %s, now()
            );
            """,
            (policy_id, tenant_id, user_id, user_id, user_id),
        )
        for run_id, idemp in [
            (run_1_id, "idemp-r1"),
            (run_2_id, "idemp-r2"),
            (run_3_id, "idemp-r3"),
        ]:
            cur.execute(
                """
                INSERT INTO evaluation_runs (
                    run_id, tenant_id, snapshot_id, ruleset_id, policy_id, workload_tier,
                    trigger_type, execution_profile, outlier_config, outlier_config_hash,
                    priority, run_status, attempt_count, lease_generation, idempotency_key, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, 'SMALL', 'ON_DEMAND', 'SPARK_K3S', '{}'::jsonb,
                    repeat('0', 64), 5, 'SUCCEEDED', 0, 0, %s, %s
                );
                """,
                (run_id, tenant_id, snapshot_id, ruleset_id, policy_id, idemp, user_id),
            )

        # 1. PUBLISHED + PUBLIC_READ assessment
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score, publication_status,
                visibility_scope, confidence_status, quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, 95.5, 'PUBLISHED', 'PUBLIC_READ', 'CONFIDENT', 'PASS', '{}'::jsonb, repeat('1', 64), now()
            );
            """,
            (assessment_pub_id, tenant_id, run_1_id, snapshot_id),
        )
        cur.execute(
            """
            INSERT INTO dimension_results (
                dimension_result_id, tenant_id, assessment_id, dimension, measurement_status,
                dimension_score, dimension_weight, total_rules, measured_rules
            ) VALUES (
                %s, %s, %s, 'COMPLETENESS', 'MEASURED', 95.5, 1.0, 10, 10
            );
            """,
            (dim_id, tenant_id, assessment_pub_id),
        )

        # 2. PUBLISHED + PRIVATE assessment
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score, publication_status,
                visibility_scope, confidence_status, quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, 90.0, 'PUBLISHED', 'PRIVATE', 'CONFIDENT', 'PASS', '{}'::jsonb, repeat('2', 64), now()
            );
            """,
            (assessment_priv_id, tenant_id, run_2_id, snapshot_id),
        )

        # 3. WITHHELD + PUBLIC_READ assessment
        cur.execute(
            """
            INSERT INTO assessments (
                assessment_id, tenant_id, run_id, snapshot_id, dq_score, publication_status,
                visibility_scope, confidence_status, quality_gate, config_hashes, assessment_hash, published_at
            ) VALUES (
                %s, %s, %s, %s, NULL, 'WITHHELD', 'PUBLIC_READ', 'NOT_CONFIDENT', 'FAIL', '{}'::jsonb, repeat('3', 64), now()
            );
            """,
            (assessment_withheld_id, tenant_id, run_3_id, snapshot_id),
        )
        db_conn.commit()

    # Public read on PUBLISHED + PUBLIC_READ assessment -> 200 OK
    resp_pub = client.get(f"/api/v1/assessments/{assessment_pub_id}/public")
    assert resp_pub.status_code == 200
    pub_data = resp_pub.json()
    assert pub_data["assessment_id"] == str(assessment_pub_id)
    assert pub_data["dq_score"] == 95.5
    assert len(pub_data["dimensions"]) == 1

    # Public read on PUBLISHED + PRIVATE assessment -> 404 (hidden by RLS)
    resp_priv = client.get(f"/api/v1/assessments/{assessment_priv_id}/public")
    assert resp_priv.status_code == 404

    # Public read on WITHHELD + PUBLIC_READ assessment -> 404 (hidden by RLS)
    resp_withheld = client.get(f"/api/v1/assessments/{assessment_withheld_id}/public")
    assert resp_withheld.status_code == 404

    # The tenant role sees no rows without tenant context; the restricted public
    # role can see only the published public projection.
    override = getattr(client.app, "dependency_overrides", {}).get(get_pg_dsn)
    dsn = override() if callable(override) else non_superuser_dsn
    with closing(get_db_connection(dsn=dsn, user=None)) as conn_gen:
        unauth_conn = next(conn_gen)
        with unauth_conn.cursor() as cur:
            cur.execute("SELECT assessment_id FROM assessments;")
            assert cur.fetchall() == []
            cur.execute("SET LOCAL ROLE dq_public_role;")
            cur.execute("SELECT assessment_id FROM assessments;")
            visible_ids = {r[0] for r in cur.fetchall()}
            assert assessment_pub_id in visible_ids
            assert assessment_priv_id not in visible_ids
            assert assessment_draft_id not in visible_ids
            assert assessment_restricted_id not in visible_ids
            assert assessment_withheld_id not in visible_ids

            cur.execute("SELECT DISTINCT assessment_id FROM dimension_results;")
            dim_assessment_ids = {r[0] for r in cur.fetchall()}
            assert dim_assessment_ids == {assessment_pub_id}


def test_cross_tenant_insert_prevented_by_rls(
    client: TestClient, db_conn, non_superuser_dsn: str
) -> None:
    """Verify RLS policy directly blocks inserting data for a different tenant."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name)
            VALUES (%s, 't_a', 'Tenant A'), (%s, 't_b', 'Tenant B');
            """,
            (tenant_a, tenant_b),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name)
            VALUES (%s, 'ua@test.com', 'pwd', 'User A');
            """,
            (user_a,),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'WORKSPACE_ADMIN', 'ACTIVE');
            """,
            (tenant_a, user_a),
        )
        db_conn.commit()

    auth_user = AuthenticatedUser(
        user_id=user_a,
        tenant_id=tenant_a,
        email="ua@test.com",
        role="WORKSPACE_ADMIN",
    )

    with (
        closing(get_db_connection(dsn=non_superuser_dsn, user=auth_user)) as conn_gen,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn = next(conn_gen)
        with conn.cursor() as cur:
            # Attempt to insert a row with tenant_b while authenticated as tenant_a
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Illegal Asset', 'illegal', 'CSV', %s, %s);
                """,
                (uuid4(), tenant_b, user_a, user_a),
            )

def test_role_and_rls_active_under_non_superuser_connection(
    non_superuser_dsn: str, db_conn, pg_dsn: str
) -> None:
    """Verify non-superuser runtime role attributes, active RLS, and fail-closed behavior."""
    # 1. Verify role attributes in PostgreSQL catalog: NOSUPERUSER NOBYPASSRLS
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolname, rolsuper, rolbypassrls
            FROM pg_roles
            WHERE rolname IN ('dq_app_role', 'dq_app_user');
            """
        )
        roles = {row[0]: {"super": row[1], "bypass": row[2]} for row in cur.fetchall()}
        assert "dq_app_role" in roles
        assert not roles["dq_app_role"]["super"], "dq_app_role must not be superuser"
        assert not roles["dq_app_role"]["bypass"], "dq_app_role must not bypass RLS"
        assert "dq_app_user" in roles
        assert not roles["dq_app_user"]["super"], "dq_app_user must not be superuser"
        assert not roles["dq_app_user"]["bypass"], "dq_app_user must not bypass RLS"

        # Verify FORCE ROW LEVEL SECURITY on sensitive tables
        cur.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname IN ('data_assets', 'assessments', 'tenant_memberships', 'dimension_results');
            """
        )
        for relname, rls, force_rls in cur.fetchall():
            assert rls, f"{relname} must have row level security enabled"
            assert force_rls, f"{relname} must have FORCE row level security"

    # 2. Verify active role and context under get_db_connection
    with closing(get_db_connection(dsn=non_superuser_dsn, user=None)) as conn_gen:
        conn = next(conn_gen)
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, session_user;")
            current_u, session_u = cur.fetchone()
            assert session_u == "dq_app_user"
            assert current_u == "dq_app_role"

            # Unauthenticated: no tenant or user context leaked
            cur.execute(
                "SELECT current_setting('app.current_user_id', true), current_setting('app.current_tenant_id', true);"
            )
            u_setting, t_setting = cur.fetchone()
            assert u_setting in ("", None)
            assert t_setting in ("", None)

    # 3. Verify Fail-Closed: unauthorized user without dq_app_role raises InsufficientPrivilege
    with db_conn.cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_unauthorized_user') THEN
                    CREATE ROLE dq_unauthorized_user WITH LOGIN PASSWORD 'unauth_secret' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END $$;
            REVOKE dq_app_role FROM dq_unauthorized_user;
            """
        )
        db_conn.commit()

    conn_info = psycopg.conninfo.conninfo_to_dict(pg_dsn)
    conn_info["user"] = "dq_unauthorized_user"
    conn_info["password"] = "unauth_secret"
    unauthorized_dsn = psycopg.conninfo.make_conninfo(**conn_info)

    # get_db_connection must fail closed and NOT swallow psycopg.Error
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        fail_gen = get_db_connection(dsn=unauthorized_dsn, user=None)
        next(fail_gen)


def test_transaction_scope_and_rollback(
    non_superuser_dsn: str, db_conn
) -> None:
    """Verify SET LOCAL transaction scoping, rollback semantics, and no context leakage."""
    tenant_id = uuid4()
    user_id = uuid4()
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name)
            VALUES (%s, %s, 'Rollback Test Tenant');
            """,
            (tenant_id, f"rb_{tenant_id.hex[:6]}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name)
            VALUES (%s, 'rb@test.com', 'pwd', 'RB User');
            """,
            (user_id,),
        )
        db_conn.commit()

    auth_user = AuthenticatedUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email="rb@test.com",
        role="WORKSPACE_ADMIN",
    )

    asset_id = uuid4()
    # 1. Transaction rolled back due to error: verify record is not written
    conn_gen = get_db_connection(dsn=non_superuser_dsn, user=auth_user)
    conn = next(conn_gen)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
            VALUES (%s, %s, 'Aborted Asset', 'aborted', 'CSV', %s, %s);
            """,
            (asset_id, tenant_id, user_id, user_id),
        )

    # Simulate an error during request handler by throwing into the generator
    with pytest.raises(RuntimeError):
        conn_gen.throw(RuntimeError("Simulated route crash"))

    # Verify asset was NOT committed due to rollback
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM data_assets WHERE asset_id = %s;", (asset_id,))
        count = cur.fetchone()[0]
        assert count == 0, "Rolled-back transaction must not persist data"

    # 2. Verify no context leakage across subsequent connections
    with closing(get_db_connection(dsn=non_superuser_dsn, user=None)) as subsequent_gen:
        subsequent_conn = next(subsequent_gen)
        with subsequent_conn.cursor() as cur:
            cur.execute(
                "SELECT current_setting('app.current_user_id', true), current_setting('app.current_tenant_id', true);"
            )
            u_setting, t_setting = cur.fetchone()
            assert u_setting in ("", None), "User context leaked"
            assert t_setting in ("", None), "Tenant context leaked"

            # Under unauthenticated connection, cannot read tenant data
            cur.execute("SELECT count(*) FROM data_assets;")
            assert cur.fetchone()[0] == 0
