"""Preview findings are paginated without returning pinned definitions or values."""
from psycopg.types.json import Jsonb

from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    client,
    org,
)
from tests.integration.conftest import _login


def test_scan_preview_findings_pagination(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    _, sid, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    rule = client.get("/api/v1/privacy-rules", headers=headers).json()["items"][0]
    scan = client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=headers, json={
        "purpose": "PREVIEW", "rule_id": rule["rule_id"], "revision": rule["revision"],
    }).json()
    rows = [{"column_name": name, "path": "", "matched_count": index} for index, name in enumerate(("a", "b", "c"), 1)]
    db_conn.execute("UPDATE privacy_scan_jobs SET state='COMPLETE',result_summary=%s WHERE scan_id=%s", (Jsonb({"findings": rows}), scan["scan_id"]))
    db_conn.commit()
    response = client.get(f"/api/v1/privacy-scans/{scan['scan_id']}/findings?page=2&page_size=2", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"items": [rows[2]], "total": 3, "page": 2, "page_size": 2}
