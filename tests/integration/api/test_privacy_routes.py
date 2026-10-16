"""Integration tests for privacy findings and asset protection policies."""
from __future__ import annotations

from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from dq_scoring.presentation.api.auth import hash_password
from tests.integration.conftest import PASSWORD, _login, client  # noqa: F401


@pytest.fixture
def org(db_conn):
    tenant_id = uuid4()
    owner_id = uuid4()
    steward_id = uuid4()
    viewer_id = uuid4()
    pw_hash = hash_password(PASSWORD)
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name) VALUES (%s, %s, %s);",
            (tenant_id, f"priv-{tenant_id.hex[:8]}", "Privacy Test Tenant"),
        )
        for uid, email in [(owner_id, "owner@priv.test"), (steward_id, "steward@priv.test"), (viewer_id, "viewer@priv.test")]:
            cur.execute(
                "INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, %s, 'Synthetic User', TRUE);",
                (uid, email, pw_hash),
            )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, 'DATA_OWNER', 'ACTIVE');",
            (tenant_id, owner_id),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, 'DATA_STEWARD', 'ACTIVE');",
            (tenant_id, steward_id),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, 'BUSINESS_VIEWER', 'ACTIVE');",
            (tenant_id, viewer_id),
        )
    db_conn.commit()
    return {
        "tenant_id": tenant_id,
        "owner": (owner_id, "owner@priv.test"),
        "steward": (steward_id, "steward@priv.test"),
        "viewer": (viewer_id, "viewer@priv.test"),
    }


def _seed_asset_and_snapshot(conn, tenant_id, user_id, with_findings=True, source_descriptor=None, columns=None, preview=None, profile=None):
    asset_id = uuid4()
    snapshot_id = uuid4()
    schema_def = {
        "columns": columns or [
            {"name": "id", "type": "STRING"},
            {"name": "email", "type": "STRING"},
            {"name": "notes", "type": "STRING"},
        ],
        "privacy": {
            "detector_revision": "builtin-v1",
            "sensitive_columns": ["email"],
        } if with_findings else {},
    }
    manifest = {
        "sensitive_scan": {
            "status": "COMPLETE" if with_findings else "UNAVAILABLE",
            "detector_revision": "builtin-v1" if with_findings else None,
            "total_rows": 10,
            "sensitive_columns": ["email"] if with_findings else [],
            "findings": [],
        }
    }
    if preview is not None:
        manifest["preview"] = preview
    if profile is not None:
        manifest["profile"] = profile
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_assets (asset_id, tenant_id, asset_name, format, slug, owner_user_id, created_by)
            VALUES (%s, %s, %s, 'CSV', %s, %s, %s);
            """,
            (asset_id, tenant_id, f"Test Asset {asset_id.hex[:8]}", f"asset-{asset_id.hex[:8]}", user_id, user_id),
        )
        cur.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_id, tenant_id, asset_id, version_number, version_status,
                source_kind, source_descriptor, content_sha256, storage_location,
                schema_definition, total_rows, total_columns, created_by, captured_at, manifest
            ) VALUES (
                %s, %s, %s, 1, 'ACTIVE',
                'OBJECT_FILE', %s, %s, 's3://test/snap.parquet',
                %s, 10, 3, %s, now(), %s
            );
            """,
            (snapshot_id, tenant_id, asset_id, Jsonb(source_descriptor or {}), "a" * 64, Jsonb(schema_def), user_id, Jsonb(manifest)),
        )
        cur.execute(
            "UPDATE data_assets SET current_snapshot_id = %s, version_count = 1 WHERE tenant_id = %s AND asset_id = %s;",
            (snapshot_id, tenant_id, asset_id),
        )

        finding_id = uuid4()
        if with_findings:
            cur.execute(
                """
                INSERT INTO sensitive_data_findings (
                    finding_id, tenant_id, snapshot_id, column_name, path,
                    category, confidence_score, status, detected_at,
                    detector_code, detector_revision, matched_count, observed_count, detection_method
                ) VALUES (
                    %s, %s, %s, 'email', '',
                    'BASIC_PERSONAL_DATA', 1.0, 'DETECTED', now(),
                    'EMAIL', 'builtin-v1', 5, 10, 'VALUE_PATTERN'
                );
                """,
                (finding_id, tenant_id, snapshot_id),
            )
    return asset_id, snapshot_id, finding_id


def test_get_sensitive_findings_complete_and_pagination(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    _asset_id, snapshot_id, finding_id = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], with_findings=True)
    db_conn.commit()
    resp = client.get(f"/api/v1/snapshots/{snapshot_id}/sensitive-findings", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_status"] == "COMPLETE"
    assert data["detector_revision"] == "builtin-v1"
    items = data["findings"]["items"]
    assert len(items) == 1
    assert items[0]["finding_id"] == str(finding_id)
    assert items[0]["column_name"] == "email"
    assert items[0]["matched_count"] == 5
    assert items[0]["observed_count"] == 10
    assert items[0]["status"] == "DETECTED"


def test_get_sensitive_findings_unavailable_for_legacy(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    _asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], with_findings=False)
    db_conn.commit()
    resp = client.get(f"/api/v1/snapshots/{snapshot_id}/sensitive-findings", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_status"] == "UNAVAILABLE"
    assert data["findings"]["total"] == 0


def test_get_sensitive_findings_forbidden_for_viewer(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["viewer"][1], org["tenant_id"])
    _asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], with_findings=True)
    db_conn.commit()
    resp = client.get(f"/api/v1/snapshots/{snapshot_id}/sensitive-findings", headers=headers)
    assert resp.status_code == 403


def test_update_finding_status_success_and_conflict(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["steward"][1], org["tenant_id"])
    _asset_id, _snapshot_id, finding_id = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], with_findings=True)
    db_conn.commit()
    # Success: update from DETECTED to CONFIRMED
    resp = client.patch(
        f"/api/v1/sensitive-findings/{finding_id}",
        headers=headers,
        json={"expected_status": "DETECTED", "status": "CONFIRMED", "reason": "Synthetic review"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CONFIRMED"

    # Stale conflict: expected_status DETECTED fails with 409
    conflict_resp = client.patch(
        f"/api/v1/sensitive-findings/{finding_id}",
        headers=headers,
        json={"expected_status": "DETECTED", "status": "DISMISSED", "reason": "Synthetic review"},
    )
    assert conflict_resp.status_code == 409
    assert "FINDING_STATUS_CONFLICT" in conflict_resp.json()["detail"]
    missing_reason = client.patch(
        f"/api/v1/sensitive-findings/{finding_id}",
        headers=headers,
        json={"expected_status": "CONFIRMED", "status": "DISMISSED"},
    )
    assert missing_reason.status_code == 422
    with db_conn.cursor() as cur:
        cur.execute("SELECT status, review_reason, reviewed_by FROM sensitive_data_findings WHERE finding_id=%s", (finding_id,))
        assert cur.fetchone() == ("CONFIRMED", "Synthetic review", org["steward"][0])
        cur.execute("SELECT count(*) FROM privacy_change_events WHERE action='FINDING_STATUS_CHANGED'")
        assert cur.fetchone()[0] == 1


def test_update_finding_status_retains_rule_and_scan_provenance(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["steward"][1], org["tenant_id"])
    _asset_id, snapshot_id, finding_id = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], with_findings=True)
    scan_id = uuid4()
    from dq_scoring.services.privacy_rule_service import ensure_initialized
    ensure_initialized(db_conn, org["tenant_id"])
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT rule_id, revision FROM privacy_detector_rules WHERE tenant_id = %s LIMIT 1",
            (org["tenant_id"],),
        )
        rule_row = cur.fetchone()
        assert rule_row is not None
        rule_id, rule_revision = rule_row[0], rule_row[1]
        cur.execute(
            """
            INSERT INTO privacy_scan_jobs (scan_id, tenant_id, snapshot_id, purpose, state, requested_by, pinned_rules, config_version, detector_digest)
            VALUES (%s, %s, %s, 'APPLY', 'COMPLETE', %s, '[]', 1, repeat('0', 64));
            """,
            (scan_id, org["tenant_id"], snapshot_id, org["owner"][0]),
        )
        cur.execute(
            """
            UPDATE sensitive_data_findings
            SET detected_by_rule_id = %s, privacy_rule_revision = %s, scan_id = %s
            WHERE finding_id = %s;
            """,
            (rule_id, rule_revision, scan_id, finding_id),
        )
    db_conn.commit()

    resp = client.patch(
        f"/api/v1/sensitive-findings/{finding_id}",
        headers=headers,
        json={"expected_status": "DETECTED", "status": "CONFIRMED", "reason": "Synthetic review with provenance"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "CONFIRMED"
    assert data["rule_id"] == str(rule_id)
    assert data["rule_revision"] == rule_revision
    assert data["scan_id"] == str(scan_id)
    assert data["historical"] is False

def test_asset_protection_policy_crud_and_version_conflict(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, _snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], with_findings=True)
    db_conn.commit()
    # 1. GET default policy (version 0)
    resp = client.get(f"/api/v1/assets/{asset_id}/protection-policy", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 0
    assert data["categories"] == []
    assert "extra_columns" not in data

    # 2. PUT valid policy
    put_resp = client.put(
        f"/api/v1/assets/{asset_id}/protection-policy",
        headers=headers,
        json={
            "expected_version": 0,
            "categories": ["BASIC_PERSONAL_DATA", "CONFIDENTIAL_BUSINESS_DATA"],
        },
    )
    assert put_resp.status_code == 200
    pdata = put_resp.json()
    assert pdata["version"] == 1
    assert "BASIC_PERSONAL_DATA" in pdata["categories"]
    assert "extra_columns" not in pdata

    # 3. PUT with stale version 0 triggers 409
    stale_resp = client.put(
        f"/api/v1/assets/{asset_id}/protection-policy",
        headers=headers,
        json={
            "expected_version": 0,
            "categories": ["BASIC_PERSONAL_DATA"],
        },
    )
    assert stale_resp.status_code == 409
    assert "POLICY_VERSION_CONFLICT" in stale_resp.json()["detail"]

    # 4. Legacy explicit-column input is rejected, not silently ignored
    legacy_resp = client.put(
        f"/api/v1/assets/{asset_id}/protection-policy",
        headers=headers,
        json={"expected_version": 1, "categories": [], "extra_columns": ["notes"]},
    )
    assert legacy_resp.status_code == 422


def _put_pinned_parquet(tenant_id, table):
    import hashlib
    import io

    import boto3
    import pyarrow.parquet as pq

    from dq_scoring.adapters.storage.s3_settings import get_s3_settings

    settings = get_s3_settings()
    buf = io.BytesIO()
    pq.write_table(table, buf)
    body = buf.getvalue()
    key = f"snapshots/{tenant_id}/{uuid4()}/canonical.parquet"
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id.get_secret_value(),
        aws_secret_access_key=settings.secret_access_key.get_secret_value(),
    )
    version = s3.put_object(Bucket=settings.bucket_snapshots, Key=key, Body=body)["VersionId"]
    canonical = {
        "bucket": settings.bucket_snapshots, "key": key, "version_id": version,
        "content_sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body), "format": "PARQUET",
    }
    return {"format": "CSV", "canonical": canonical}, s3, settings


def test_masked_parquet_export_uses_pinned_canonical_and_classification(client, org, db_conn):  # noqa: F811
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"id": ["1", "2"], "email": ["alice@example.com", None], "code": ["SYN-01", ""]})
    src_desc, s3, settings = _put_pinned_parquet(org["tenant_id"], table)
    cols = [{"name": "id", "type": "STRING"}, {"name": "email", "type": "STRING"}, {"name": "code", "type": "STRING"}]
    asset_id, snapshot_id, _ = _seed_asset_and_snapshot(
        db_conn, org["tenant_id"], org["owner"][0], with_findings=True, source_descriptor=src_desc, columns=cols,
    )
    db_conn.commit()
    headers = _login(client, org["owner"][1], org["tenant_id"])
    classified = client.put(f"/api/v1/assets/{asset_id}/column-classifications", headers=headers, json={
        "snapshot_id": str(snapshot_id), "expected_version": 0,
        "changes": [{"column_name": "code", "category": "CONFIDENTIAL_BUSINESS_DATA", "reason": "Synthetic code"}],
    })
    assert classified.status_code == 200

    export_resp = client.get(f"/api/v1/assets/{asset_id}/masked-export?snapshot_id={snapshot_id}", headers=headers)
    assert export_resp.status_code == 200, export_resp.text
    assert "attachment" in export_resp.headers.get("content-disposition", "")
    assert export_resp.headers.get("cache-control") == "no-store"
    data = pq.read_table(io.BytesIO(export_resp.content)).to_pydict()
    assert data == {"id": ["1", "2"], "email": ["[REDACTED]", None], "code": ["[REDACTED]", ""]}

    # Object replaced after registration: integrity check fails closed instead of reading latest.
    s3.put_object(Bucket=settings.bucket_snapshots, Key=src_desc["canonical"]["key"], Body=b"not parquet")
    assert client.get(f"/api/v1/assets/{asset_id}/masked-export?snapshot_id={snapshot_id}", headers=headers).status_code == 409


def test_masked_export_rejects_unpinned_and_foreign_snapshot(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset_id, _snapshot_id, _ = _seed_asset_and_snapshot(
        db_conn, org["tenant_id"], org["owner"][0], source_descriptor={"bucket": "x", "key": "raw.csv"},
    )
    _other_asset, other_snapshot, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    unpinned = client.get(f"/api/v1/assets/{asset_id}/masked-export", headers=headers)
    assert unpinned.status_code == 409
    assert "SNAPSHOT_REIMPORT_REQUIRED" in unpinned.text
    foreign = client.get(f"/api/v1/assets/{asset_id}/masked-export?snapshot_id={other_snapshot}", headers=headers)
    assert foreign.status_code == 404
