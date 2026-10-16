"""Integration tests for dataset import API integrity, expiry, fencing, and crash recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.auth import AuthenticatedUser, create_access_token
from dq_scoring.presentation.api.config import get_api_settings


@pytest.fixture
def test_user_id() -> UUID:
    return uuid4()


@pytest.fixture
def auth_headers(test_tenant_id, test_user_id) -> dict[str, str]:
    user = AuthenticatedUser(
        user_id=test_user_id,
        tenant_id=test_tenant_id,
        email="integrity_engineer@example.com",
        role="DATA_ENGINEER",
    )
    settings = get_api_settings()
    token = create_access_token(user, secret_key=settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded_tenant_and_users(db_conn: psycopg.Connection, test_tenant_id: UUID, test_user_id: UUID):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, %s, 'ENTERPRISE', 'ACTIVE')
            ON CONFLICT (tenant_id) DO NOTHING;
            """,
            (test_tenant_id, f"tenant_{test_tenant_id.hex[:6]}", "Integrity Test Tenant"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, 'integrity_engineer@example.com', 'dummy_hash', 'Integrity Engineer', TRUE)
            ON CONFLICT (user_id) DO NOTHING;
            """,
            (test_user_id,),
        )
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (str(test_tenant_id),))
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE')
            ON CONFLICT (tenant_id, user_id) DO NOTHING;
            """,
            (test_tenant_id, test_user_id),
        )
        db_conn.commit()


# -----------------------------------------------------------------------------
# 1. Expiration Invariants
# -----------------------------------------------------------------------------

def test_expired_session_rejected_across_lifecycle(
    client: TestClient,
    db_conn: psycopg.Connection,
    seeded_tenant_and_users,
    auth_headers: dict[str, str],
    test_tenant_id: UUID,
    test_user_id: UUID,
):
    upload_id = uuid4()
    past_time = datetime.now(UTC) - timedelta(hours=2)

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dataset_upload_sessions (
                upload_id, tenant_id, asset_name, client_request_id,
                format, original_filename, size_bytes, staging_key,
                multipart_id, status, manifest, created_by,
                created_at, expires_at, updated_at
            ) VALUES (
                %s, %s, 'Expired Asset', %s,
                'CSV', 'expired.csv', 100, 'imports/test/expired.csv',
                'mp-expired', 'INITIATED', '{}'::jsonb, %s,
                %s, %s, %s
            );
            """,
            (upload_id, test_tenant_id, uuid4(), test_user_id, past_time, past_time, past_time),
        )
        db_conn.commit()

    # GET session indicates IMPORT_EXPIRED
    get_resp = client.get(f"/api/v1/imports/{upload_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["error_code"] == "IMPORT_EXPIRED"

    # Part upload rejected
    part_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": "4"},
        content=b"test",
    )
    assert part_resp.status_code == 409
    assert part_resp.json()["error_code"] == "IMPORT_EXPIRED"

    # Complete rejected
    complete_resp = client.post(
        f"/api/v1/imports/{upload_id}/complete",
        headers=auth_headers,
        json={"parts": [{"part_number": 1, "etag": "etag-1"}]},
    )
    assert complete_resp.status_code == 409
    assert complete_resp.json()["error_code"] == "IMPORT_EXPIRED"

    # Register rejected
    register_resp = client.post(
        f"/api/v1/imports/{upload_id}/register",
        headers=auth_headers,
        json={"acknowledged_warnings": []},
    )
    assert register_resp.status_code == 409
    assert register_resp.json()["error_code"] == "IMPORT_EXPIRED"


# -----------------------------------------------------------------------------
# 2. Part Replay vs Checksum Conflict
# -----------------------------------------------------------------------------

def test_part_replay_and_conflict(
    client: TestClient,
    seeded_tenant_and_users,
    auth_headers: dict[str, str],
):
    # Initiate multipart session
    init_resp = client.post(
        "/api/v1/imports",
        headers=auth_headers,
        json={
            "client_request_id": str(uuid4()),
            "asset_name": "Part Test Asset",
            "format": "CSV",
            "original_filename": "parts.csv",
            "size_bytes": 5,
        },
    )
    assert init_resp.status_code == 201
    upload_id = init_resp.json()["upload_id"]

    # Upload part 1
    content1 = b"12345"
    p1_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(content1))},
        content=content1,
    )
    assert p1_resp.status_code == 200
    etag1 = p1_resp.json()["etag"]

    # Replay part 1 with identical content -> idempotent 200 with same ETag
    replay_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(content1))},
        content=content1,
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["etag"] == etag1

    # Upload part 1 with different content -> 409 PART_CHECKSUM_MISMATCH
    conflict_content = b"54321"
    conflict_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(conflict_content))},
        content=conflict_content,
    )
    assert conflict_resp.status_code == 409
    assert conflict_resp.json()["error_code"] == "PART_CHECKSUM_MISMATCH"


def test_completion_requires_full_uploaded_payload(client, seeded_tenant_and_users, auth_headers):
    response = client.post("/api/v1/imports", headers=auth_headers, json={
        "client_request_id": str(uuid4()), "asset_name": "Incomplete upload",
        "format": "CSV", "original_filename": "incomplete.csv", "size_bytes": 10,
    })
    upload_id = response.json()["upload_id"]
    result = client.post(f"/api/v1/imports/{upload_id}/complete", headers=auth_headers, json={"parts": [{"part_number": 1, "etag": "missing"}]})
    assert result.status_code == 409
    assert result.json()["error_code"] == "IMPORT_STATE_CONFLICT"
    state = client.get(f"/api/v1/imports/{upload_id}", headers=auth_headers).json()
    assert state["status"] == "INITIATED"


# -----------------------------------------------------------------------------
# 3. Complete Multipart Crash Recovery
# -----------------------------------------------------------------------------

def test_complete_multipart_crash_recovery(
    client: TestClient,
    seeded_tenant_and_users,
    auth_headers: dict[str, str],
):
    # Initiate session
    init_resp = client.post(
        "/api/v1/imports",
        headers=auth_headers,
        json={
            "client_request_id": str(uuid4()),
            "asset_name": "Crash Recovery Asset",
            "format": "CSV",
            "original_filename": "recovery.csv",
            "size_bytes": 15,
        },
    )
    assert init_resp.status_code == 201
    session_data = init_resp.json()
    upload_id = session_data["upload_id"]

    content = b"id,val\n1,alpha\n"
    part_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(content))},
        content=content,
    )
    assert part_resp.status_code == 200
    etag = part_resp.json()["etag"]

    # Normal completion transitions to STAGED (202)
    comp_resp = client.post(
        f"/api/v1/imports/{upload_id}/complete",
        headers=auth_headers,
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert comp_resp.status_code == 202
    assert comp_resp.json()["status"] == "STAGED"

    # Idempotent re-complete returns STAGED (202)
    recomp_resp = client.post(
        f"/api/v1/imports/{upload_id}/complete",
        headers=auth_headers,
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert recomp_resp.status_code == 202
    assert recomp_resp.json()["status"] == "STAGED"


# -----------------------------------------------------------------------------
# 4. Warning Acknowledgment and Registration
# -----------------------------------------------------------------------------

def test_register_single_column_input_warning_guard(
    client: TestClient,
    db_conn: psycopg.Connection,
    seeded_tenant_and_users,
    auth_headers: dict[str, str],
    test_tenant_id: UUID,
    test_user_id: UUID,
):
    upload_id = uuid4()
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=24)

    source_desc = {
        "bucket": "test-bucket",
        "key": "test/source.csv",
        "version_id": "v-1",
        "content_sha256": "a" * 64,
        "size_bytes": 50,
        "format": "CSV",
        "canonical": {
            "bucket": "test-bucket",
            "key": "test/canonical.parquet",
            "version_id": "v-2",
            "content_sha256": "b" * 64,
            "size_bytes": 100,
            "format": "PARQUET",
        },
        "normalization_version": 1,
    }

    manifest = {
        "source_descriptor": source_desc,
        "columns": [{"name": "single_col", "type": "STRING"}],
        "exact_row_count": 5,
        "warnings": ["SINGLE_COLUMN_INPUT"],
    }

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dataset_upload_sessions (
                upload_id, tenant_id, asset_name, client_request_id,
                format, original_filename, size_bytes, staging_key,
                status, manifest, created_by, created_at, expires_at, updated_at
            ) VALUES (
                %s, %s, 'Single Col Asset', %s,
                'CSV', 'single.csv', 50, 'imports/single.csv',
                'VERIFIED', %s, %s, %s, %s, %s
            );
            """,
            (upload_id, test_tenant_id, uuid4(), psycopg.types.json.Jsonb(manifest), test_user_id, now, expires_at, now),
        )
        db_conn.commit()

    # Attempt registration without acknowledging warning -> 422 WARNING_ACKNOWLEDGMENT_REQUIRED
    reg_fail = client.post(
        f"/api/v1/imports/{upload_id}/register",
        headers=auth_headers,
        json={"acknowledged_warnings": []},
    )
    assert reg_fail.status_code == 422
    assert reg_fail.json()["error_code"] == "WARNING_ACKNOWLEDGMENT_REQUIRED"

    # Register with acknowledged warning -> 200 OK
    reg_ok = client.post(
        f"/api/v1/imports/{upload_id}/register",
        headers=auth_headers,
        json={"acknowledged_warnings": ["SINGLE_COLUMN_INPUT"]},
    )
    assert reg_ok.status_code == 200
    assert "snapshot_id" in reg_ok.json()


def test_existing_source_cannot_reference_foreign_tenant(client, seeded_tenant_and_users, auth_headers):
    from dq_scoring.adapters.storage.s3_settings import get_s3_settings
    result = client.post("/api/v1/imports", headers=auth_headers, json={
        "client_request_id": str(uuid4()), "asset_name": "Foreign source",
        "format": "CSV", "original_filename": "test.csv", "size_bytes": 10,
        "source": {"bucket": get_s3_settings().bucket_staging, "key": f"imports/{uuid4()}/secret.csv"},
    })
    assert result.status_code == 404
    assert result.json()["error_code"] == "RESOURCE_NOT_FOUND"


def test_nonadmin_cannot_request_global_staging_scope(client, seeded_tenant_and_users, auth_headers):
    response = client.get("/api/v1/storage/objects?scope=staging", headers=auth_headers)
    assert response.status_code == 403
