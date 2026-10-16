"""Synthetic privacy workspace contract regressions."""
from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    client,
    org,
)
from tests.integration.conftest import _login


def test_classification_updates_are_versioned_and_atomic(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    url = f"/api/v1/assets/{asset_id}/column-classifications"
    body = {"snapshot_id": str(snapshot_id), "expected_version": 0, "changes": [
        {"column_name": "notes", "category": "CONFIDENTIAL_BUSINESS_DATA", "reason": "Synthetic classification"},
    ]}
    response = client.put(url, headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert client.put(url, headers=headers, json=body).status_code == 409
    read = client.get(f"/api/v1/snapshots/{snapshot_id}/column-classifications", headers=headers)
    assert read.status_code == 200
    notes = next(c for c in read.json()["columns"] if c["column_name"] == "notes")
    assert notes["declared_category"] == "CONFIDENTIAL_BUSINESS_DATA"
    assert notes["protected"] is True
    invalid = client.put(url, headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 1,
        "changes": [
            {"column_name": "notes", "category": "STANDARD_DATA", "reason": "Synthetic correction"},
            {"column_name": "missing", "category": "STANDARD_DATA", "reason": "Synthetic invalid scope"},
        ],
    })
    assert invalid.status_code == 422
    unchanged = client.get(f"/api/v1/snapshots/{snapshot_id}/column-classifications", headers=headers).json()
    assert unchanged["version"] == 1
    assert next(c for c in unchanged["columns"] if c["column_name"] == "notes")["declared_category"] == "CONFIDENTIAL_BUSINESS_DATA"


def test_standard_declaration_does_not_override_detection(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    response = client.put(f"/api/v1/assets/{asset_id}/column-classifications", headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 0,
        "changes": [{"column_name": "email", "category": "STANDARD_DATA", "reason": "Synthetic conflicting declaration"}],
    })
    assert response.status_code == 200
    columns = client.get(f"/api/v1/snapshots/{snapshot_id}/column-classifications", headers=headers).json()["columns"]
    email = next(c for c in columns if c["column_name"] == "email")
    assert email["conflict"] is True
    assert email["protected"] is True
    assert "BASIC_PERSONAL_DATA" in email["effective_categories"]


def test_declared_sensitive_column_masks_existing_preview(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, snapshot_id, _ = _seed_asset_and_snapshot(
        db_conn, org["tenant_id"], org["owner"][0],
        preview=[{"id": "A", "notes": "SYN-01", "email": "qa@example.com"}],
    )
    db_conn.commit()
    response = client.put(f"/api/v1/assets/{asset_id}/column-classifications", headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 0,
        "changes": [{"column_name": "notes", "category": "CONFIDENTIAL_BUSINESS_DATA", "reason": "Synthetic output protection"}],
    })
    assert response.status_code == 200
    preview = client.get(f"/api/v1/snapshots/{snapshot_id}/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["preview"][0]["notes"] == "[REDACTED]"
    assert "SYN-01" not in preview.text
    assert preview.headers.get("cache-control") == "no-store"


def test_registered_import_session_reflects_current_classification(client, org, db_conn):  # noqa: F811
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from psycopg.types.json import Jsonb

    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    upload_id, now = uuid4(), datetime.now(UTC)
    manifest = {
        "columns": [{"name": "id"}, {"name": "email"}, {"name": "notes"}],
        "preview": [{"id": "A", "email": "[REDACTED]", "notes": "SYN-01"}],
        "profile": {"sample_rows": 1, "is_sample": True, "total_rows": 1, "columns": [
            {"name": "notes", "type_hint": "STRING", "min": "SYN-01", "max": "SYN-01", "sample_rows": 1},
        ]},
    }
    db_conn.execute(
        """INSERT INTO dataset_upload_sessions (
               upload_id, tenant_id, asset_id, asset_name, format, original_filename, size_bytes, staging_key,
               status, manifest, registered_snapshot_id, created_by, created_at, expires_at, updated_at
           ) VALUES (%s, %s, %s, 'Synthetic', 'CSV', 'syn.csv', 10, 'imports/syn.csv',
                     'REGISTERED', %s, %s, %s, %s, %s, %s)""",
        (upload_id, org["tenant_id"], asset_id, Jsonb(manifest), snapshot_id, org["owner"][0], now, now + timedelta(days=1), now),
    )
    db_conn.commit()
    assert client.put(f"/api/v1/assets/{asset_id}/column-classifications", headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 0,
        "changes": [{"column_name": "notes", "category": "CONFIDENTIAL_BUSINESS_DATA", "reason": "Synthetic"}],
    }).status_code == 200

    for url in (f"/api/v1/imports/{upload_id}", "/api/v1/imports"):
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        assert "SYN-01" not in response.text
        assert response.headers.get("cache-control") == "no-store"
    session = client.get(f"/api/v1/imports/{upload_id}", headers=headers).json()
    assert session["preview"][0]["notes"] == "[REDACTED]"
    assert "min" not in session["profile"]["columns"][0]


def test_finding_review_invalidates_stale_classification_write(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, snapshot_id, finding_id = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    reviewed = client.patch(f"/api/v1/sensitive-findings/{finding_id}", headers=headers, json={
        "expected_status": "DETECTED", "status": "DISMISSED", "reason": "Synthetic false positive",
    })
    assert reviewed.status_code == 200
    current = client.get(f"/api/v1/snapshots/{snapshot_id}/column-classifications", headers=headers)
    assert current.json()["version"] == 1
    stale = client.put(f"/api/v1/assets/{asset_id}/column-classifications", headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 0,
        "changes": [{"column_name": "email", "category": "STANDARD_DATA", "reason": "Synthetic"}],
    })
    assert stale.status_code == 409
    assert next(c for c in current.json()["columns"] if c["column_name"] == "email")["declared_category"] is None


def test_snapshot_profile_removes_protected_extrema_without_losing_counts(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, snapshot_id, _ = _seed_asset_and_snapshot(
        db_conn, org["tenant_id"], org["owner"][0], preview=[{"notes": "SYN-01", "id": "A"}],
        profile={"is_sample": True, "sample_rows": 1, "total_rows": 10, "columns": [
            {"name": "notes", "min": "SYN-01", "max": "SYN-01", "null_count": 0, "non_null_count": 1, "sample_rows": 1},
            {"name": "id", "min": "A", "max": "A", "sample_rows": 1},
        ]},
    )
    db_conn.commit()
    assert client.put(f"/api/v1/assets/{asset_id}/column-classifications", headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 0,
        "changes": [{"column_name": "notes", "category": "CONFIDENTIAL_BUSINESS_DATA", "reason": "Synthetic"}],
    }).status_code == 200
    response = client.get(f"/api/v1/snapshots/{snapshot_id}/preview", headers=headers)
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["sample_rows"] == 1
    assert profile["total_rows"] == 10
    assert profile["columns"][0] == {"name": "notes", "null_count": 0, "non_null_count": 1, "sample_rows": 1}
    assert profile["columns"][1]["min"] == "A"
    assert "SYN-01" not in response.text
