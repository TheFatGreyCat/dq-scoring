"""Integration tests for Row-Level Security (RLS) and Multi-Tenancy Defense-in-Depth."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.errors import ForeignKeyViolation, InsufficientPrivilege

from dq_scoring.adapters.db.tenant_context import set_tenant_context


def _seed_tenant_and_user(
    conn: psycopg.Connection, tenant_id: UUID, user_id: UUID
) -> None:
    """Helper to seed a tenant and associated user (as superuser before switching to app role)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING;
            """,
            (tenant_id, f"tenant-{tenant_id}", f"Tenant {tenant_id}"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING;
            """,
            (
                user_id,
                f"user-{user_id}@test.local",
                "$argon2id$seedhash",
                f"User {user_id}",
            ),
        )


def test_tenant_isolation_data_assets_and_snapshots(pg_dsn: str) -> None:
    """Verify that Tenant A and Tenant B cannot see each other's assets and snapshots."""
    tenant_a = uuid4()
    user_a = uuid4()
    asset_a = uuid4()
    snap_a = uuid4()

    tenant_b = uuid4()
    user_b = uuid4()
    asset_b = uuid4()
    snap_b = uuid4()

    # 1. Seed base data as admin
    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant_and_user(admin_conn, tenant_a, user_a)
        _seed_tenant_and_user(admin_conn, tenant_b, user_b)

        # Seed asset & snapshot for Tenant A
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Asset A', 'asset-a', 'CSV', %s, %s);
                """,
                (asset_a, tenant_a, user_a, user_a),
            )
            cur.execute(
                """
                INSERT INTO dataset_snapshots (
                    snapshot_id, tenant_id, asset_id, version_number,
                    source_kind, source_descriptor, content_sha256,
                    storage_location, schema_definition, total_rows, total_columns,
                    created_by, captured_at
                ) VALUES (%s, %s, %s, 1, 'OBJECT_FILE', '{}'::jsonb, %s, 's3://snap-a', '{}'::jsonb, 100, 2, %s, now());
                """,
                (snap_a, tenant_a, asset_a, "a" * 64, user_a),
            )

            # Seed asset & snapshot for Tenant B
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Asset B', 'asset-b', 'CSV', %s, %s);
                """,
                (asset_b, tenant_b, user_b, user_b),
            )
            cur.execute(
                """
                INSERT INTO dataset_snapshots (
                    snapshot_id, tenant_id, asset_id, version_number,
                    source_kind, source_descriptor, content_sha256,
                    storage_location, schema_definition, total_rows, total_columns,
                    created_by, captured_at
                ) VALUES (%s, %s, %s, 1, 'OBJECT_FILE', '{}'::jsonb, %s, 's3://snap-b', '{}'::jsonb, 200, 3, %s, now());
                """,
                (snap_b, tenant_b, asset_b, "b" * 64, user_b),
            )
        admin_conn.commit()

    # 2. Test Tenant A visibility under dq_app_role
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction():
            set_tenant_context(app_conn, tenant_a)
            cur = app_conn.cursor()

            cur.execute("SELECT asset_id FROM data_assets;")
            asset_rows = cur.fetchall()
            assert len(asset_rows) == 1
            assert asset_rows[0][0] == asset_a

            cur.execute("SELECT snapshot_id FROM dataset_snapshots;")
            snap_rows = cur.fetchall()
            assert len(snap_rows) == 1
            assert snap_rows[0][0] == snap_a

    # 3. Test Tenant B visibility under dq_app_role
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction():
            set_tenant_context(app_conn, tenant_b)
            cur = app_conn.cursor()

            cur.execute("SELECT asset_id FROM data_assets;")
            asset_rows = cur.fetchall()
            assert len(asset_rows) == 1
            assert asset_rows[0][0] == asset_b

            cur.execute("SELECT snapshot_id FROM dataset_snapshots;")
            snap_rows = cur.fetchall()
            assert len(snap_rows) == 1
            assert snap_rows[0][0] == snap_b


def test_fail_closed_when_tenant_context_missing(pg_dsn: str) -> None:
    """Verify fail-closed policy: queries return 0 rows and inserts fail when no tenant context is set."""
    tenant_id = uuid4()
    user_id = uuid4()

    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant_and_user(admin_conn, tenant_id, user_id)
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Asset Test', 'asset-test', 'CSV', %s, %s);
                """,
                (uuid4(), tenant_id, user_id, user_id),
            )
        admin_conn.commit()

    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")

        # 1. SELECT without tenant context returns 0 rows (Fail-Closed)
        with app_conn.transaction():
            cur = app_conn.cursor()
            cur.execute("SELECT * FROM data_assets;")
            assert cur.fetchall() == []

            cur.execute("SELECT * FROM dataset_snapshots;")
            assert cur.fetchall() == []

        # 2. INSERT without tenant context is rejected by RLS WITH CHECK policy
        with (
            pytest.raises(InsufficientPrivilege),
            app_conn.transaction(),
            app_conn.cursor() as cur,
        ):
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Asset Unauthorized', 'asset-unauth', 'CSV', %s, %s);
                """,
                (uuid4(), tenant_id, user_id, user_id),
            )


def test_cross_tenant_insert_spoofing_rejected(pg_dsn: str) -> None:
    """Verify that Tenant A cannot insert data on behalf of Tenant B."""
    tenant_a = uuid4()
    user_a = uuid4()
    tenant_b = uuid4()
    user_b = uuid4()

    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant_and_user(admin_conn, tenant_a, user_a)
        _seed_tenant_and_user(admin_conn, tenant_b, user_b)
        admin_conn.commit()

    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        set_tenant_context(app_conn, tenant_a)
        with (
            pytest.raises(InsufficientPrivilege),
            app_conn.transaction(),
            app_conn.cursor() as cur,
        ):
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Spoofed Asset', 'spoofed-asset', 'CSV', %s, %s);
                """,
                (uuid4(), tenant_b, user_a, user_a),
            )


def test_composite_foreign_key_cross_tenant_prevention(pg_dsn: str) -> None:
    """Verify defense-in-depth: composite (tenant_id, id) FK prevents linking cross-tenant objects."""
    tenant_a = uuid4()
    user_a = uuid4()
    asset_a = uuid4()

    tenant_b = uuid4()
    user_b = uuid4()
    asset_b = uuid4()
    snap_b = uuid4()

    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant_and_user(admin_conn, tenant_a, user_a)
        _seed_tenant_and_user(admin_conn, tenant_b, user_b)

        with admin_conn.cursor() as cur:
            # Seed asset & snapshot for Tenant B
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Asset B', 'asset-b', 'CSV', %s, %s);
                """,
                (asset_b, tenant_b, user_b, user_b),
            )
            cur.execute(
                """
                INSERT INTO dataset_snapshots (
                    snapshot_id, tenant_id, asset_id, version_number,
                    source_kind, source_descriptor, content_sha256,
                    storage_location, schema_definition, total_rows, total_columns,
                    created_by, captured_at
                ) VALUES (%s, %s, %s, 1, 'OBJECT_FILE', '{}'::jsonb, %s, 's3://snap-b', '{}'::jsonb, 200, 3, %s, now());
                """,
                (snap_b, tenant_b, asset_b, "b" * 64, user_b),
            )

            # Tenant A seeds asset, ruleset, and policy
            ruleset_a = uuid4()
            policy_a = uuid4()
            cur.execute(
                """
                INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
                VALUES (%s, %s, 'Asset A', 'asset-a', 'CSV', %s, %s);
                """,
                (asset_a, tenant_a, user_a, user_a),
            )
            cur.execute(
                """
                INSERT INTO rulesets (ruleset_id, tenant_id, asset_id, version, config_hash, status, created_by, submitted_by, submitted_at, approved_by, approved_at)
                VALUES (%s, %s, %s, '1.0', 'hash-a', 'ACTIVE', %s, %s, now(), %s, now());
                """,
                (ruleset_a, tenant_a, asset_a, user_a, user_a, user_a),
            )
            cur.execute(
                """
                INSERT INTO scoring_policies (policy_id, tenant_id, version, config_hash, status, created_by, submitted_by, submitted_at, approved_by, approved_at, dimension_weights, publication_threshold, gate_rules)
                VALUES (%s, %s, '1.0', 'hash-p', 'ACTIVE', %s, %s, now(), %s, now(), '{}'::jsonb, 0.8, '{}'::jsonb);
                """,
                (policy_a, tenant_a, user_a, user_a, user_a),
            )
        admin_conn.commit()

        # Tenant A attempts to launch evaluation run referencing Tenant B's snapshot (snap_b)
        # Violates FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id)
        with (
            pytest.raises(ForeignKeyViolation),
            admin_conn.transaction(),
            admin_conn.cursor() as cur,
        ):
            cur.execute(
                """
                INSERT INTO evaluation_runs (
                        run_id, tenant_id, snapshot_id, ruleset_id, policy_id,
                        workload_tier, trigger_type, execution_profile, outlier_config,
                        outlier_config_hash, priority, run_status, attempt_count,
                        lease_generation, idempotency_key, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        'SMALL', 'ON_DEMAND', 'SPARK_K3S', '{}'::jsonb,
                        'outlier-hash', 5, 'QUEUED', 0,
                        0, 'run-idemp-1', %s
                    );
                    """,
                (uuid4(), tenant_a, snap_b, ruleset_a, policy_a, user_a),
            )


def test_template_inheritance_system_and_tenant(pg_dsn: str) -> None:
    """Verify template inheritance: system templates are shared; private templates are isolated."""
    sys_template_id = uuid4()
    tenant_a = uuid4()
    user_a = uuid4()
    template_a = uuid4()

    tenant_b = uuid4()
    user_b = uuid4()
    template_b = uuid4()

    with psycopg.connect(pg_dsn) as admin_conn:
        _seed_tenant_and_user(admin_conn, tenant_a, user_a)
        _seed_tenant_and_user(admin_conn, tenant_b, user_b)

        with admin_conn.cursor() as cur:
            # Seed system template (tenant_id IS NULL)
            cur.execute(
                """
                INSERT INTO rule_catalog_templates (
                    template_id, tenant_id, template_code, name,
                    default_dimension, rule_type, parameter_schema, default_null_policy, is_advisory_default
                ) VALUES (%s, NULL, 'SYS_NON_NULL', 'System Non Null', 'COMPLETENESS', 'NON_NULL', '{}'::jsonb, 'FAIL', FALSE);
                """,
                (sys_template_id,),
            )

            # Seed Tenant A custom template
            cur.execute(
                """
                INSERT INTO rule_catalog_templates (
                    template_id, tenant_id, template_code, name,
                    default_dimension, rule_type, parameter_schema, default_null_policy, is_advisory_default
                ) VALUES (%s, %s, 'CUSTOM_RULE_A', 'Tenant A Custom', 'VALIDITY', 'DOMAIN_RANGE', '{}'::jsonb, 'FAIL', FALSE);
                """,
                (template_a, tenant_a),
            )

            # Seed Tenant B custom template
            cur.execute(
                """
                INSERT INTO rule_catalog_templates (
                    template_id, tenant_id, template_code, name,
                    default_dimension, rule_type, parameter_schema, default_null_policy, is_advisory_default
                ) VALUES (%s, %s, 'CUSTOM_RULE_B', 'Tenant B Custom', 'VALIDITY', 'DOMAIN_RANGE', '{}'::jsonb, 'FAIL', FALSE);
                """,
                (template_b, tenant_b),
            )
        admin_conn.commit()

    # Query under dq_app_role as Tenant A
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction():
            set_tenant_context(app_conn, tenant_a)
            cur = app_conn.cursor()
            cur.execute(
                "SELECT template_id FROM rule_catalog_templates ORDER BY template_code;"
            )
            templates = [row[0] for row in cur.fetchall()]

            # Must see System template AND Tenant A template, but NOT Tenant B template
            assert sys_template_id in templates
            assert template_a in templates
            assert template_b not in templates

    # Query under dq_app_role as Tenant B
    with psycopg.connect(pg_dsn) as app_conn:
        app_conn.execute("SET ROLE dq_app_role;")
        with app_conn.transaction():
            set_tenant_context(app_conn, tenant_b)
            cur = app_conn.cursor()
            cur.execute(
                "SELECT template_id FROM rule_catalog_templates ORDER BY template_code;"
            )
            templates = [row[0] for row in cur.fetchall()]

            # Must see System template AND Tenant B template, but NOT Tenant A template
            assert sys_template_id in templates
            assert template_b in templates
            assert template_a not in templates
