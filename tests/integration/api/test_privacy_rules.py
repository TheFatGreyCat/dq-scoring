"""Synthetic tenant-scoped detector rule revision and validation regressions."""
from uuid import uuid4

from tests.integration.api.test_privacy_routes import client, org  # noqa: F401
from tests.integration.conftest import _login


def _custom_rule(code="SYNTHETIC_CODE"):
    return {"code": code, "kind": "VALUE_PATTERN", "category": "CONFIDENTIAL_BUSINESS_DATA", "enabled": True,
            "pattern": r"SYN-\d+", "match_mode": "SEARCH", "case_sensitive": True, "columns": ["notes"]}


def test_rule_revisions_preserve_identity_and_reject_stale_editor(client, org):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    created = client.post("/api/v1/privacy-rules", headers=headers, json=_custom_rule())
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["revision"] == 1
    duplicate = client.post("/api/v1/privacy-rules", headers=headers, json=_custom_rule())
    assert duplicate.status_code == 409
    update = {k: v for k, v in _custom_rule().items() if k not in ("code", "kind")}
    update.update(expected_revision=1, enabled=False)
    changed = client.put(f"/api/v1/privacy-rules/{first['rule_id']}", headers=headers, json=update)
    assert changed.status_code == 200, changed.text
    second = changed.json()
    assert second["rule_id"] == first["rule_id"]
    assert second["revision"] == 2
    assert second["enabled"] is False
    assert second["config_version"] == first["config_version"] + 1
    assert client.put(f"/api/v1/privacy-rules/{first['rule_id']}", headers=headers, json=update).status_code == 409
    listed = client.get("/api/v1/privacy-rules", headers=headers).json()
    assert next(r for r in listed["items"] if r["rule_id"] == first["rule_id"])["revision"] == 2


def test_invalid_rule_patterns_and_payloads_do_not_echo_literals(client, org):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    for pattern in (r"(?=SENSITIVE_LITERAL)", r"(SENSITIVE_LITERAL)\1"):
        body = _custom_rule()
        body["pattern"] = pattern
        response = client.post("/api/v1/privacy-rules", headers=headers, json=body)
        assert response.status_code == 422
        assert "SENSITIVE_LITERAL" not in response.text
        assert "INVALID_PRIVACY_PATTERN" in response.text
    body = _custom_rule()
    body.update(kind="SENSITIVE_LITERAL", pattern="SENSITIVE_LITERAL")
    response = client.post("/api/v1/privacy-rules", headers=headers, json=body)
    assert response.status_code == 422
    assert "SENSITIVE_LITERAL" not in response.text


def test_detector_definitions_are_editor_only_and_unknown_rule_is_not_found(client, org):  # noqa: F811
    viewer = _login(client, org["viewer"][1], org["tenant_id"])
    assert client.get("/api/v1/privacy-rules", headers=viewer).status_code == 403
    assert client.post("/api/v1/privacy-rules", headers=viewer, json=_custom_rule()).status_code == 403
    editor = _login(client, org["steward"][1], org["tenant_id"])
    update = {k: v for k, v in _custom_rule().items() if k not in ("code", "kind")}
    update["expected_revision"] = 1
    assert client.put(f"/api/v1/privacy-rules/{uuid4()}", headers=editor, json=update).status_code == 404
