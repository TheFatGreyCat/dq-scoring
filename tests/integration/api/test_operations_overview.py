from uuid import uuid4

from dq_scoring.presentation.api.auth import AuthenticatedUser, create_access_token
from dq_scoring.presentation.api.config import get_api_settings
from tests.integration.api.test_operations_routes import headers


def _auth_headers(tenant_id, role="DATA_ENGINEER", user_id=None):
    uid = user_id or uuid4()
    user = AuthenticatedUser(
        user_id=uid, tenant_id=tenant_id, email=f"{uid.hex[:8]}@example.test", role=role
    )
    token = create_access_token(user, get_api_settings().jwt_secret)
    return {"Authorization": f"Bearer {token}"}


def _seed_tenant(db_conn, role="DATA_ENGINEER"):
    tenant_id, user_id = uuid4(), uuid4()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s, %s, %s, 'ENTERPRISE', 'ACTIVE')",
            (tenant_id, f"ten_{tenant_id.hex[:12]}", "Second Tenant"),
        )
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, 'hash', 'Second User', TRUE)",
            (user_id, f"eng_{user_id.hex[:12]}@example.test"),
        )
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (str(tenant_id),))
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, %s, 'ACTIVE')",
            (tenant_id, user_id, role),
        )
        db_conn.commit()
    return _auth_headers(tenant_id, role, user_id=user_id)


def _create_import(client, auth_headers, asset_name="Test Asset", filename="test.csv"):
    resp = client.post(
        "/api/v1/imports",
        headers=auth_headers,
        json={
            "client_request_id": str(uuid4()),
            "asset_name": asset_name,
            "format": "CSV",
            "original_filename": filename,
            "size_bytes": 100,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_empty_viewer_overview_has_real_zero_and_no_import_fields(client):
    _, viewer = headers("VIEWER")
    response = client.get("/api/v1/overview", headers=viewer)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["counts"]["assets"] == 0
    assert data["counts"]["snapshots"] == 0
    assert data["counts"]["runs"] == {status: 0 for status in ("QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")}
    assert data["recent_runs"] == []
    assert data["import_counts"] is None and data["recent_imports"] is None


def test_overview_with_recent_imports_returns_200_and_summaries(client, tenant):
    session = _create_import(client, tenant.creator, asset_name="Test Asset", filename="test.csv")

    overview_resp = client.get("/api/v1/overview", headers=tenant.creator)
    assert overview_resp.status_code == 200, overview_resp.text
    overview_data = overview_resp.json()
    assert len(overview_data["recent_imports"]) == 1
    summary = overview_data["recent_imports"][0]
    assert summary["upload_id"] == session["upload_id"]
    assert summary["status"] == "INITIATED"
    assert summary["asset_name"] == "Test Asset"
    assert summary["format"] == "CSV"
    assert summary["original_filename"] == "test.csv"
    assert summary["size_bytes"] == 100
    assert "preview" not in summary and "profile" not in summary


def test_overview_tenants_isolated_in_imports_and_counts(client, tenant, db_conn):
    tenant_2_headers = _seed_tenant(db_conn)

    assert client.post("/api/v1/assets", headers=tenant.creator, json={"name": "Tenant 1 Asset"}).status_code == 201
    session_1 = _create_import(client, tenant.creator, asset_name="Tenant 1 Import", filename="t1.csv")

    assert client.post("/api/v1/assets", headers=tenant_2_headers, json={"name": "Tenant 2 Asset A"}).status_code == 201
    assert client.post("/api/v1/assets", headers=tenant_2_headers, json={"name": "Tenant 2 Asset B"}).status_code == 201
    session_2 = _create_import(client, tenant_2_headers, asset_name="Tenant 2 Import", filename="t2.csv")
    db_conn.execute(
        "UPDATE dataset_upload_sessions SET status='VERIFIED' WHERE upload_id IN (%s, %s)",
        (session_1["upload_id"], session_2["upload_id"]),
    )
    db_conn.commit()

    resp_1 = client.get("/api/v1/overview", headers=tenant.creator)
    assert resp_1.status_code == 200, resp_1.text
    data_1 = resp_1.json()
    assert data_1["counts"]["assets"] == 1
    assert len(data_1["recent_imports"]) == 1
    assert data_1["recent_imports"][0]["upload_id"] == session_1["upload_id"]
    assert data_1["recent_imports"][0]["asset_name"] == "Tenant 1 Import"
    assert data_1["import_counts"] == {
        status: int(status == "VERIFIED")
        for status in ("STAGED", "VERIFYING", "VERIFIED", "REJECTED", "FAILED")
    }

    resp_2 = client.get("/api/v1/overview", headers=tenant_2_headers)
    assert resp_2.status_code == 200, resp_2.text
    data_2 = resp_2.json()
    assert data_2["counts"]["assets"] == 2
    assert len(data_2["recent_imports"]) == 1
    assert data_2["recent_imports"][0]["upload_id"] == session_2["upload_id"]
    assert data_2["recent_imports"][0]["asset_name"] == "Tenant 2 Import"
    assert data_2["import_counts"] == data_1["import_counts"]


def test_viewer_with_populated_workspace_sees_null_import_fields(client, tenant):
    assert client.post("/api/v1/assets", headers=tenant.creator, json={"name": "Populated Asset"}).status_code == 201
    _create_import(client, tenant.creator, asset_name="Populated Import", filename="pop.csv")

    viewer_headers = _auth_headers(tenant.tenant_id, "VIEWER")
    resp = client.get("/api/v1/overview", headers=viewer_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["counts"]["assets"] == 1
    assert data["import_counts"] is None
    assert data["recent_imports"] is None


def test_importer_empty_workspace_sees_empty_list_and_zero_counts(client):
    _, importer = headers("DATA_ENGINEER")
    resp = client.get("/api/v1/overview", headers=importer)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["counts"]["assets"] == 0
    assert data["counts"]["snapshots"] == 0
    assert data["counts"]["runs"] == {status: 0 for status in ("QUEUED", "LEASED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")}
    assert data["recent_runs"] == []
    assert data["recent_imports"] == []
    assert data["import_counts"] == {status: 0 for status in ("STAGED", "VERIFYING", "VERIFIED", "REJECTED", "FAILED")}
