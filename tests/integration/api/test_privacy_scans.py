"""Privacy scan queue and preview isolation contracts with synthetic snapshots."""
from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    client,
    org,
)
from tests.integration.conftest import _login


def test_apply_queue_is_idempotent_and_fail_closed(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    _asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    url = f"/api/v1/snapshots/{snapshot_id}/privacy-scans"
    queued = client.post(url, headers=headers, json={"purpose": "APPLY"})
    assert queued.status_code == 202, queued.text
    first = queued.json()
    assert first["state"] == "QUEUED"
    assert "pinned_rules" not in first
    repeated = client.post(url, headers=headers, json={"purpose": "APPLY"})
    assert repeated.status_code == 202
    assert repeated.json()["scan_id"] == first["scan_id"]
    state = client.get(f"/api/v1/privacy-scans/{first['scan_id']}", headers=headers)
    assert state.status_code == 200
    assert state.json()["state"] == "QUEUED"
    classifications = client.get(f"/api/v1/snapshots/{snapshot_id}/column-classifications", headers=headers).json()
    assert classifications["scan_status"] == "QUEUED"
    assert all(c["protected"] for c in classifications["columns"])


def test_preview_queue_does_not_change_effective_snapshot_state(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    _asset_id, snapshot_id, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    rules = client.get("/api/v1/privacy-rules", headers=headers)
    assert rules.status_code == 200
    rule = rules.json()["items"][0]
    queued = client.post(f"/api/v1/snapshots/{snapshot_id}/privacy-scans", headers=headers, json={
        "purpose": "PREVIEW", "rule_id": rule["rule_id"], "revision": rule["revision"],
    })
    assert queued.status_code == 202, queued.text
    before = client.get(f"/api/v1/snapshots/{snapshot_id}/column-classifications", headers=headers).json()
    assert before["scan_status"] == "COMPLETE"
    assert next(c for c in before["columns"] if c["column_name"] == "id")["protected"] is False
    forbidden = _login(client, org["viewer"][1], org["tenant_id"])
    assert client.get(f"/api/v1/privacy-scans/{queued.json()['scan_id']}", headers=forbidden).status_code == 403
