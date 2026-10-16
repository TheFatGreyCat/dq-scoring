"""Privacy metadata remains tenant-isolated at both API and PostgreSQL boundaries."""
import os
from uuid import uuid4

import psycopg
import pytest

from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    client,
    org,
)
from tests.integration.conftest import _login


def test_cross_tenant_privacy_reads_and_mutations_are_hidden(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    asset, sid, finding = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    rules = client.get("/api/v1/privacy-rules", headers=headers).json()
    rule = rules["items"][0]
    scan = client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=headers, json={"purpose": "APPLY"}).json()
    classification = {"snapshot_id": str(sid), "expected_version": 1, "changes": [
        {"column_name": "notes", "category": "CONFIDENTIAL_BUSINESS_DATA", "reason": "Synthetic isolation"},
    ]}
    assert client.put(f"/api/v1/assets/{asset}/column-classifications", headers=headers, json=classification).status_code == 200
    other = uuid4()
    db_conn.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES(%s,%s,'Synthetic tenant B')", (other, f"syn-{other.hex}"))
    db_conn.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role,status) VALUES(%s,%s,'DATA_OWNER','ACTIVE')", (other, org["owner"][0]))
    db_conn.commit()
    other_headers = _login(client, org["owner"][1], other)
    for path in (f"snapshots/{sid}/column-classifications", f"snapshots/{sid}/sensitive-findings", f"privacy-scans/{scan['scan_id']}"):
        assert client.get(f"/api/v1/{path}", headers=other_headers).status_code == 404
    assert client.put(f"/api/v1/assets/{asset}/column-classifications", headers=other_headers, json=classification).status_code == 404
    assert client.patch(f"/api/v1/sensitive-findings/{finding}", headers=other_headers, json={"expected_status": "DETECTED", "status": "DISMISSED", "reason": "Synthetic"}).status_code == 404
    assert client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=other_headers, json={"purpose": "APPLY"}).status_code == 404
    with psycopg.connect(os.environ["DQ_TEST_POSTGRES_DSN"]) as conn:
        conn.execute("SET LOCAL ROLE dq_app_role")
        conn.execute("SELECT set_config('app.current_tenant_id',%s,true)", (str(other),))
        for table in ("asset_column_classifications", "privacy_change_events", "privacy_detector_configs", "privacy_detector_rules", "privacy_scan_jobs"):
            assert conn.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (org["tenant_id"],)).fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("INSERT INTO asset_column_classifications(tenant_id,asset_id,column_name,category,updated_by,reason) VALUES(%s,%s,'forbidden','STANDARD_DATA',%s,'Synthetic')", (org["tenant_id"], asset, org["owner"][0]))
    assert rule["rule_id"] not in str(client.get("/api/v1/privacy-rules", headers=other_headers).json())
