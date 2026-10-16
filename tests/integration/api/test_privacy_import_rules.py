"""Import scans pin the configured rules and use final canonical column names."""
from tests.integration.api.test_privacy_routes import client, org  # noqa: F401
from tests.integration.conftest import _login
from tests.support.object_snapshots import register_snapshot_via_api


def test_import_records_configured_custom_detector_provenance(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    rule = client.post("/api/v1/privacy-rules", headers=headers, json={
        "code": "SYNTHETIC_COMMENT", "kind": "VALUE_PATTERN", "category": "CONFIDENTIAL_BUSINESS_DATA",
        "enabled": True, "pattern": "SYN-[0-9]+", "match_mode": "SEARCH", "case_sensitive": True,
        "columns": ["comment"],
    })
    assert rule.status_code == 201
    snapshot = register_snapshot_via_api(
        client, headers, content_or_path=b'{"id":"A","comment":"contact SYN-01 for testing"}\n', file_format="JSONL",
    )
    result = client.get(f"/api/v1/snapshots/{snapshot['snapshot_id']}/sensitive-findings", headers=headers)
    assert result.status_code == 200
    finding = next((f for f in result.json()["findings"]["items"] if f["detector_code"] == "SYNTHETIC_COMMENT"), None)
    assert finding is not None
    assert str(finding["rule_id"]) == rule.json()["rule_id"]
    assert finding["rule_revision"] == 1
    assert finding["scan_id"] is not None
    assert result.json()["config_version"] == rule.json()["config_version"]
    preview = client.get(f"/api/v1/snapshots/{snapshot['snapshot_id']}/preview", headers=headers)
    assert "SYN-01" not in preview.text
