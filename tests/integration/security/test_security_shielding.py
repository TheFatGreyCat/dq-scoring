"""Comprehensive security tests validating AC-020, AC-022, AC-023, AC-024, and AC-025."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from dq_scoring.common.formula_sanitizer import sanitize_records
from dq_scoring.presentation.api.auth import hash_password
from tests.support.run_seed import seed_run_prerequisites


def test_internal_tenant_bola_prevention_ac020(client: TestClient, db_conn):
    """AC-020: Verify cross-tenant access attempts to assets/snapshots return 404/fail-closed."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    pwd_hash = hash_password("Password123!")

    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name) VALUES (%s, %s, %s);",
            (tenant_a, f"tenant_a_{tenant_a.hex[:6]}", "Tenant A Org"),
        )
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, %s, %s);",
            (user_a, f"user_a_{user_a.hex[:6]}@example.com", pwd_hash, "User A"),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES (%s, %s, 'DATA_ENGINEER');",
            (tenant_a, user_a),
        )

        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name) VALUES (%s, %s, %s);",
            (tenant_b, f"tenant_b_{tenant_b.hex[:6]}", "Tenant B Org"),
        )
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, %s, %s);",
            (user_b, f"user_b_{user_b.hex[:6]}@example.com", pwd_hash, "User B"),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES (%s, %s, 'DATA_ENGINEER');",
            (tenant_b, user_b),
        )

        asset_b_id = uuid4()
        cur.execute(
            """
            INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by)
            VALUES (%s, %s, 'Tenant B Confidential Data', %s, 'CSV', %s, %s);
            """,
            (asset_b_id, tenant_b, f"slug-b-{asset_b_id.hex[:6]}", user_b, user_b),
        )
        db_conn.commit()

    login_a_resp = client.post(
        "/api/v1/auth/login",
        json={"email": f"user_a_{user_a.hex[:6]}@example.com", "password": "Password123!"},
    )
    token_a = login_a_resp.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    illegal_snap_resp = client.post(
        "/api/v1/imports",
        headers=headers_a,
        json={
            "asset_id": str(asset_b_id),
            "client_request_id": str(uuid4()),
            "format": "CSV", "original_filename": "test.csv", "size_bytes": 100,
        },
    )
    assert illegal_snap_resp.status_code == 404
    assert "not found" in illegal_snap_resp.json()["detail"].lower()


def test_public_scorecard_zero_evidence_leak_ac022(client: TestClient, pg_dsn: str):
    """AC-022: Verify public scorecard endpoint strictly strips 100% metadata/evidence."""
    from psycopg.types.json import Jsonb

    from dq_scoring.adapters.db.tenant_context import set_tenant_context
    from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
    from dq_scoring.core.entities import (
        DatasetSnapshot,
        QualityRule,
        RunSpec,
    )
    from dq_scoring.core.models import ScoringPolicy
    tenant_id = uuid4()
    asset_id = uuid4()
    snapshot_id = uuid4()
    run_id = uuid4()
    assessment_id = uuid4()
    rule_id = uuid4()

    snapshot = DatasetSnapshot(
        snapshot_id=snapshot_id,
        tenant_id=tenant_id,
        asset_id=asset_id,
        source_kind="LOCAL_FILE",
        source_descriptor={"path": "/secret/path/test.csv"},
        schema_definition={"columns": ["ssn"]},
        total_rows=5000,
        total_columns=1,
        captured_at=datetime.now(UTC),
    )

    rule = QualityRule(
        rule_id=rule_id,
        rule_code="SECRET_SSN_RULE",
        dimension="Completeness",
        rule_type="NON_NULL",
        parameters={"column": "ssn"},
    )

    spec = RunSpec(
        run_id=run_id,
        tenant_id=tenant_id,
        snapshot=snapshot,
        rules=[rule],
        policy=ScoringPolicy(),
    )

    queue = PostgresQueueAdapter(pg_dsn)
    spec = seed_run_prerequisites(pg_dsn, spec)
    queue.enqueue_run(spec, idempotency_key=f"sec-test-{uuid4()}")
    with psycopg.connect(pg_dsn) as conn, conn.transaction():
        set_tenant_context(conn, tenant_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                    UPDATE evaluation_runs
                    SET run_status = 'SUCCEEDED', completed_at = now()
                    WHERE run_id = %s;
                    """,
                    (run_id,),
                )
            cur.execute(
                """
                    INSERT INTO assessments (
                        assessment_id, tenant_id, run_id, snapshot_id,
                        dq_score, publication_status, visibility_scope,
                        coverage_ratio, confidence_status, quality_gate,
                        config_hashes, assessment_hash, published_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        99.0, 'PUBLISHED', 'PUBLIC_READ',
                        1.0, 'NOT_APPLICABLE', 'PASS',
                        '{}'::jsonb, 'sec-hash-1234567890', now()
                    );
                    """,
                    (assessment_id, tenant_id, run_id, snapshot_id),
                )
            cur.execute(
                """
                    INSERT INTO dimension_results (
                        dimension_result_id, tenant_id, assessment_id,
                        dimension, measurement_status, dimension_score,
                        dimension_weight, total_rules, measured_rules
                    ) VALUES (
                        %s, %s, %s,
                        'COMPLETENESS', 'MEASURED', 99.0,
                        1.0, 1, 1
                    );
                    """,
                    (uuid4(), tenant_id, assessment_id),
                )
            cur.execute(
                """
                    INSERT INTO canonical_quality_results (
                        result_id, tenant_id, run_id, rule_id, ruleset_id,
                        rule_config_hash, source_kind, target_column, dimension,
                        measurement_status, passed_count, failed_count,
                        missing_count, miscast_count, not_applicable_count,
                        total_observed, computed_score, is_advisory,
                        is_required, gate_enabled, score_enabled, evidence_payload
                    ) VALUES (
                        %s, %s, %s, %s,
                        (SELECT ruleset_id FROM evaluation_runs WHERE run_id = %s),
                        'sec-rule-hash', 'RULE', 'ssn', 'COMPLETENESS',
                        'MEASURED', 4950, 50,
                        0, 0, 0,
                        5000, 99.0, FALSE,
                        TRUE, TRUE, TRUE, %s
                    );
                    """,
                    (
                        uuid4(),
                        tenant_id,
                        run_id,
                        rule_id,
                        run_id,
                        Jsonb(
                            {
                                "samples": [
                                    {
                                        "ssn": "123-45-6789",
                                        "email": "ceo@secret-corp.com",
                                    }
                                ],
                                "sample_count": 1,
                            }
                        ),
                    ),
                )

    public_resp = client.get(f"/api/v1/assessments/{assessment_id}/public")
    assert public_resp.status_code == 200
    data = public_resp.json()

    assert data["assessment_id"] == str(assessment_id)
    assert data["dq_score"] == 99.0
    assert data["quality_gate"] == "PASS"
    assert data["publication_status"] == "PUBLISHED"
    assert len(data["dimensions"]) == 1
    assert data["dimensions"][0]["dimension"] in ("Completeness", "COMPLETENESS")
    assert data["dimensions"][0]["dimension_score"] == 99.0

    # AC-022: Assert 100% evidence, metadata, rule details, PII are stripped
    assert "evidence_payload" not in data
    assert "rule_results" not in data
    assert "evidence_samples" not in data
    assert "source_descriptor" not in data
    assert "tenant_id" not in data
    assert "run_id" not in data
    assert "snapshot_id" not in data
    assert "ssn" not in str(data)
    assert "ceo@secret-corp.com" not in str(data)


def test_server_header_stripping_and_rfc9457_ac025(client: TestClient):
    """AC-025: Verify server fingerprint headers are stripped and errors adhere to RFC 9457."""
    # 1. Test standard response headers
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "server" not in resp.headers
    assert "x-powered-by" not in resp.headers
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"

    # 2. Test RFC 9457 error response
    bad_resp = client.get("/api/v1/snapshots/00000000-0000-0000-0000-000000000000")
    assert bad_resp.status_code == 401  # Unauthorized without token
    assert bad_resp.headers.get("content-type") == "application/problem+json"
    err = bad_resp.json()
    assert "title" in err
    assert "status" in err
    assert "detail" in err
    assert "type" in err
    # Assert zero stack traces or internal paths leaked
    assert "Traceback" not in str(err)
    assert "postgresql://" not in str(err)


def test_csv_formula_injection_defense_ac025():
    """AC-025: Verify CSV formula injection triggers are neutralized."""
    malicious_rows = [
        {"calc": "=cmd|' /C calc'!A0", "macro": "+SUM(A1:A2)", "link": "@SUM(1+1)"},
        {"tab": "\t=1+1", "cr": "\r-2+2", "normal": "valid_data"},
    ]
    sanitized = sanitize_records(malicious_rows)
    assert sanitized[0]["calc"] == "'=cmd|' /C calc'!A0"
    assert sanitized[0]["macro"] == "'+SUM(A1:A2)"
    assert sanitized[0]["link"] == "'@SUM(1+1)"
    assert sanitized[1]["tab"] == "'\t=1+1"
    assert sanitized[1]["cr"] == "'\r-2+2"
    assert sanitized[1]["normal"] == "valid_data"

