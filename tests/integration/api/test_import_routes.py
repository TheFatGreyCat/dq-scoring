"""Integration tests for MinIO dataset import API routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.presentation.api.auth import AuthenticatedUser, create_access_token
from dq_scoring.presentation.api.config import get_api_settings
from dq_scoring.workers.import_worker import ImportWorker


@pytest.fixture
def test_user_id() -> UUID:
    return uuid4()


@pytest.fixture
def auth_headers(test_tenant_id, test_user_id) -> dict[str, str]:
    user = AuthenticatedUser(
        user_id=test_user_id,
        tenant_id=test_tenant_id,
        email="engineer@example.com",
        role="DATA_ENGINEER",
    )
    settings = get_api_settings()
    token = create_access_token(user, secret_key=settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_headers(test_tenant_id) -> dict[str, str]:
    user = AuthenticatedUser(
        user_id=uuid4(),
        tenant_id=test_tenant_id,
        email="viewer@example.com",
        role="BUSINESS_VIEWER",
    )
    settings = get_api_settings()
    token = create_access_token(user, secret_key=settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded_tenant_and_users(db_conn, test_tenant_id, test_user_id):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, %s, 'ENTERPRISE', 'ACTIVE')
            ON CONFLICT (tenant_id) DO NOTHING;
            """,
            (test_tenant_id, f"tenant_{test_tenant_id.hex[:6]}", "Test Tenant"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, 'engineer@example.com', 'dummy_hash', 'Test Engineer', TRUE)
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
def test_business_viewer_is_forbidden(client: TestClient, seeded_tenant_and_users, viewer_headers):
    # Viewer cannot list storage objects
    resp = client.get("/api/v1/storage/objects", headers=viewer_headers)
    assert resp.status_code == 403

    # Viewer cannot create imports
    resp = client.post(
        "/api/v1/imports",
        headers=viewer_headers,
        json={
            "client_request_id": str(uuid4()),
            "asset_name": "Test Asset",
            "format": "CSV",
            "original_filename": "test.csv",
            "size_bytes": 100,
        },
    )
    assert resp.status_code == 403


def test_storage_objects_listing(client: TestClient, seeded_tenant_and_users, auth_headers):
    resp = client.get("/api/v1/storage/objects", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


def test_import_lifecycle_and_idempotency(client: TestClient, seeded_tenant_and_users, auth_headers):
    client_req_id = uuid4()
    payload = {
        "client_request_id": str(client_req_id),
        "asset_name": "Taxi Trips",
        "format": "CSV",
        "original_filename": "trips.csv",
        "size_bytes": 1024,
    }

    # 1. Create import session
    resp = client.post("/api/v1/imports", headers=auth_headers, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    upload_id = data["upload_id"]
    assert data["status"] == "INITIATED"
    assert data["asset_name"] == "Taxi Trips"

    # 2. Idempotent call with same client_request_id returns existing session
    resp2 = client.post("/api/v1/imports", headers=auth_headers, json=payload)
    assert resp2.status_code == 201
    assert resp2.json()["upload_id"] == upload_id

    # 3. Conflicting call with same client_request_id but different format returns 409
    conflicting = {**payload, "format": "PARQUET"}
    resp_conflict = client.post("/api/v1/imports", headers=auth_headers, json=conflicting)
    assert resp_conflict.status_code == 409
    assert resp_conflict.json()["error_code"] == "IMPORT_STATE_CONFLICT"

    # 4. Upload part 1
    part_content = b"header1,header2\nval1,val2\n" + (b"0" * (1024 - 26))
    upload_part_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(part_content))},
        content=part_content,
    )
    assert upload_part_resp.status_code == 200
    etag1 = upload_part_resp.json()["etag"]
    assert etag1

    # 5. Replay part 1 with identical content returns 200 with same ETag
    replay_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(part_content))},
        content=part_content,
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["etag"] == etag1

    # 6. Replay part 1 with different content returns 409
    diff_content = b"x" * len(part_content)
    diff_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(diff_content))},
        content=diff_content,
    )
    assert diff_resp.status_code == 409
    assert diff_resp.json()["error_code"] == "PART_CHECKSUM_MISMATCH"

    # 7. Complete import
    complete_resp = client.post(
        f"/api/v1/imports/{upload_id}/complete",
        headers=auth_headers,
        json={"parts": [{"part_number": 1, "etag": etag1}]},
    )
    assert complete_resp.status_code == 202
    assert complete_resp.json()["status"] == "STAGED"

    # 8. Check session status via GET
    get_resp = client.get(f"/api/v1/imports/{upload_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "STAGED"


def test_import_abort(client: TestClient, seeded_tenant_and_users, auth_headers):
    client_req_id = uuid4()
    payload = {
        "client_request_id": str(client_req_id),
        "asset_name": "Abort Test",
        "format": "CSV",
        "original_filename": "abort.csv",
        "size_bytes": 500,
    }

    resp = client.post("/api/v1/imports", headers=auth_headers, json=payload)
    assert resp.status_code == 201
    upload_id = resp.json()["upload_id"]

    abort_resp = client.post(f"/api/v1/imports/{upload_id}/abort", headers=auth_headers)
    assert abort_resp.status_code == 200
    assert abort_resp.json()["status"] == "ABORTED"
def test_import_worker_process_and_register_snapshot(client: TestClient, db_conn, seeded_tenant_and_users, auth_headers):
    # 1. Initiate CSV import
    client_req_id = uuid4()
    csv_bytes = b"trip_id,amount,pickup_date\nt1,25.50,2026-10-01\nt2,-5.00,2026-10-02\nt3,,2026-10-03\n"
    payload = {
        "client_request_id": str(client_req_id),
        "asset_name": "Yellow Taxi Trips",
        "format": "CSV",
        "original_filename": "yellow_taxi.csv",
        "size_bytes": len(csv_bytes),
    }

    resp = client.post("/api/v1/imports", headers=auth_headers, json=payload)
    assert resp.status_code == 201
    upload_id = resp.json()["upload_id"]

    # 2. Upload part
    part_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**auth_headers, "Content-Length": str(len(csv_bytes))},
        content=csv_bytes,
    )
    assert part_resp.status_code == 200
    etag = part_resp.json()["etag"]

    # 3. Complete part upload -> STAGED
    complete_resp = client.post(
        f"/api/v1/imports/{upload_id}/complete",
        headers=auth_headers,
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete_resp.status_code == 202

    # 4. Worker claims and processes session -> VERIFIED
    store = S3ObjectStoreAdapter(settings=get_s3_settings())
    worker = ImportWorker(store=store, worker_id="test-worker")
    claimed = worker.claim_next_session(db_conn)
    assert claimed is not None
    assert str(claimed["upload_id"]) == upload_id

    worker.process_session(db_conn, claimed)
    db_conn.commit()

    # 5. Check session status is now VERIFIED with preview and profile
    verified_resp = client.get(f"/api/v1/imports/{upload_id}", headers=auth_headers)
    assert verified_resp.status_code == 200
    v_data = verified_resp.json()
    assert v_data["status"] == "VERIFIED"
    assert len(v_data["preview"]) == 3
    assert v_data["profile"]["total_rows"] == 3

    # 6. Register immutable snapshot
    reg_resp = client.post(
        f"/api/v1/imports/{upload_id}/register",
        headers=auth_headers,
        json={"acknowledged_warnings": []},
    )
    assert reg_resp.status_code == 200
    snap_data = reg_resp.json()
    assert snap_data["source_kind"] == "OBJECT_FILE"
    assert snap_data["total_rows"] == 3
    assert snap_data["total_columns"] == 3
    assert "s3a://" in snap_data["source_descriptor"]["canonical"]["s3a_uri"]

    # 7. Re-registering same session returns same snapshot response idempotently
    reg_resp2 = client.post(
        f"/api/v1/imports/{upload_id}/register",
        headers=auth_headers,
        json={"acknowledged_warnings": []},
    )
    assert reg_resp2.status_code == 200
    assert reg_resp2.json()["snapshot_id"] == snap_data["snapshot_id"]
