"""Unit tests for template_pack CLI commands."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from dq_scoring.presentation.cli.template_pack import main


def test_cli_validate_finance_pack(monkeypatch, tmp_path):
    base = tmp_path / "synthetic"
    base.with_suffix(".aff").write_bytes(b"SET UTF-8\n")
    base.with_suffix(".dic").write_text("3\nthanh\nto\u00e1n\npayment\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "revision": "synthetic-v1",
        "languages": {
            "vi": [{"base_path": str(base), "aff_sha256": hashlib.sha256(b"SET UTF-8\n").hexdigest(), "dic_sha256": hashlib.sha256(base.with_suffix(".dic").read_bytes()).hexdigest()}],
            "en": [{"base_path": str(base), "aff_sha256": hashlib.sha256(b"SET UTF-8\n").hexdigest(), "dic_sha256": hashlib.sha256(base.with_suffix(".dic").read_bytes()).hexdigest()}],
        },
    }))
    monkeypatch.setenv("DQ_TEXT_DICTIONARY_MANIFEST", str(manifest))

    pack_file = Path("src/dq_scoring/data/templates/finance_quality_v1.json")
    code = main(["validate", "--file", str(pack_file)])
    assert code == 0


def test_cli_validate_missing_file(capsys):
    code = main(["validate", "--file", "nonexistent_pack.json"])
    assert code == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_cli_validate_outcome_mismatch(tmp_path, capsys):
    bad_pack = tmp_path / "bad.json"
    bad_pack.write_text(json.dumps({
        "pack_code": "BAD_PACK",
        "revision": 1,
        "templates": [
            {
                "template_code": "FAIL_TEMPLATE",
                "name": "Fail Template",
                "domain": "GENERAL",
                "data_type": "MASTER_DATA",
                "target_use_case": "TEST",
                "description": "test",
                "rules_payload": [
                    {
                        "rule_code": "r1",
                        "dimension": "COMPLETENESS",
                        "rule_type": "NON_NULL",
                        "parameters": {"column": "$col"},
                    }
                ],
                "provenance": {
                    "kind": "ENGINEERING_CONVENTION",
                    "source_uri": "https://example.com/spec",
                    "source_title": "Title",
                    "source_version": "1.0",
                    "source_section": "1",
                    "retrieved_at": "2026-10-15T00:00:00Z",
                    "license": "MIT",
                    "applicability": "test",
                },
                "placeholder_schema": {
                    "$col": {"type": "COLUMN", "required": True}
                },
                "examples": [
                    {"input": {"x": "ok"}, "bindings": {"$col": "x"}, "expected": {"r1": "passed"}},
                    {"input": {"x": "ok"}, "bindings": {"$col": "x"}, "expected": {"r1": "failed"}},
                ],
            }
        ],
    }))

    code = main(["validate", "--file", str(bad_pack)])
    assert code == 1
    err = capsys.readouterr().err
    assert "expected outcome 'failed', got 'passed'" in err


def test_cli_import_requires_token(monkeypatch, capsys):
    monkeypatch.delenv("DQ_TEMPLATE_API_TOKEN", raising=False)
    pack_file = Path("src/dq_scoring/data/templates/finance_quality_v1.json")
    code = main(["import", "--file", str(pack_file), "--api-url", "http://127.0.0.1:18000"])
    assert code == 1
    err = capsys.readouterr().err
    assert "DQ_TEMPLATE_API_TOKEN" in err


def test_cli_import_posts_to_api_and_does_not_echo_token(monkeypatch, capsys):
    token = "secret-synthetic-token-value-12345"
    monkeypatch.setenv("DQ_TEMPLATE_API_TOKEN", token)
    pack_file = Path("src/dq_scoring/data/templates/finance_quality_v1.json")

    mock_resp = {
        "status": "IMPORTED",
        "created": 12,
        "existing": 0,
        "items": [{"template_id": "00000000-0000-0000-0000-000000000001"} for _ in range(12)],
    }

    class FakeResponse:
        status_code = 200
        text = json.dumps(mock_resp)

        def json(self):
            return mock_resp

    with patch("httpx.post", return_value=FakeResponse()) as mock_post:
        code = main(["import", "--file", str(pack_file), "--api-url", "http://127.0.0.1:18000"])
        assert code == 0
        mock_post.assert_called_once()
        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == f"Bearer {token}"

    out, err = capsys.readouterr()
    assert token not in out
    assert token not in err
    parsed = json.loads(out)
    assert parsed["status"] == "IMPORTED"
    assert parsed["created"] == 12
