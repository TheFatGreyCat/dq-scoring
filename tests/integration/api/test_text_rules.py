from tests.support.object_snapshots import register_snapshot_via_api


def test_structured_rules_and_advisory_storage(client, tenant):
    snapshot = register_snapshot_via_api(client, tenant.creator, content_or_path=b'{"text":"synthetic","payload":{"amount":10}}\n', file_format="JSONL", filename="synthetic.jsonl")
    base = {"asset_id": snapshot["asset_id"], "name": "Synthetic extended rules"}
    response = client.post("/api/v1/rulesets", headers=tenant.creator, json={**base, "rules": [
        {"rule_code":"JSON", "dimension":"VALIDITY", "rule_type":"JSON_FIELD", "parameters":{"column":"payload", "path":"/amount", "check":"RANGE", "min":"0"}},
        {"rule_code":"MOJIBAKE", "dimension":"VALIDITY", "rule_type":"TEXT_QUALITY", "parameters":{"column":"text", "check":"MOJIBAKE"}, "is_required":True, "is_critical":True},
    ]})
    assert response.status_code == 201, response.text
    advisory = response.json()["rules"][1]
    assert advisory["is_advisory"] and not advisory["gate_enabled"] and not advisory["score_enabled"]
    assert advisory["contribution_weight"] == 0
    rejected = client.post("/api/v1/rulesets", headers=tenant.creator, json={**base, "rules":[{"rule_code":"INVALID", "dimension":"VALIDITY", "rule_type":"TYPE_PARSE", "parameters":{"column":"payload"}}]})
    assert rejected.status_code == 422
    assert "STRUCTURED_COLUMN_REQUIRES_JSON_RULE" in rejected.text


def test_dictionary_metadata_requires_authentication(client, tenant):
    assert client.get("/api/v1/text-dictionaries").status_code == 401
    response = client.get("/api/v1/text-dictionaries", headers=tenant.creator)
    assert response.status_code == 200
    assert set(response.json()) == {"status", "revision", "languages", "error_code"}
