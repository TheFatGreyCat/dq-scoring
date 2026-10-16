from uuid import uuid4

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.core.entities import QualityRule
from tests.support.object_snapshots import create_test_snapshot


def test_text_and_nested_rule_counts(tmp_path):
    source = tmp_path / "synthetic.jsonl"
    source.write_text(
        '{"text":"Thanh toán hợp lệ?","payload":{"amount":10,"tags":["a","b"]}}\n'
        '{"text":"Thanh�toán","payload":{"amount":-1,"tags":["a","a"]}}\n'
        '{"text":"Thanh\\u0001toán","payload":{"tags":[]}}\n'
        '{"text":null,"payload":null}\n', encoding="utf-8",
    )
    snapshot = create_test_snapshot(source, file_format="JSONL")
    parameters = [
        ("TEXT_QUALITY", {"column": "text", "check": "REPLACEMENT_CHARACTER"}),
        ("TEXT_QUALITY", {"column": "text", "check": "CONTROL_CHARACTER"}),
        ("JSON_FIELD", {"column": "payload", "path": "/amount", "check": "RANGE", "min": "0"}),
        ("JSON_ARRAY", {"column": "payload", "path": "/tags", "min_items": 1, "unique_items": True}),
    ]
    rules = [QualityRule(rule_id=uuid4(), rule_code=f"SYNTHETIC_{i}", dimension="VALIDITY", rule_type=kind, parameters=params) for i, (kind, params) in enumerate(parameters)]
    results = PySparkComputeAdapter().execute_rules(snapshot, rules)
    assert [(r.counts.passed, r.counts.failed, r.counts.missing) for r in results] == [(2, 1, 1), (2, 1, 1), (1, 1, 2), (1, 2, 1)]
    assert all(r.counts.total_observed == 4 for r in results)


def test_spelling_broadcast_and_pinned_replay(tmp_path, monkeypatch):
    import hashlib
    import json

    from dq_scoring.adapters.compute.spelling_dictionary import (
        SpellingDictionaryManager,
    )
    base = tmp_path / "synthetic"
    aff = b"SET UTF-8\n"
    dic = "3\nthanh\ntoán\npayment\n".encode()
    base.with_suffix(".aff").write_bytes(aff)
    base.with_suffix(".dic").write_bytes(dic)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"revision": "synthetic-v1", "languages": {"vi": [{"base_path": str(base), "aff_sha256": hashlib.sha256(aff).hexdigest(), "dic_sha256": hashlib.sha256(dic).hexdigest()}]}}))
    monkeypatch.setenv("DQ_TEXT_DICTIONARY_MANIFEST", str(manifest))
    source = tmp_path / "words.jsonl"
    source.write_text('\n'.join(json.dumps({"text": text}, ensure_ascii=False) for text in ("Thanh toán", "Thanh toán", "paymnt", " ", "123?!")))
    snapshot = create_test_snapshot(source, file_format="JSONL")
    params = {"column": "text", "language": "vi", "dictionary_revision": "synthetic-v1", "dictionary_digests": SpellingDictionaryManager().get_digests("synthetic-v1", "vi")}
    rule = QualityRule(rule_id=uuid4(), rule_code="SYNTHETIC_SPELLING", dimension="VALIDITY", rule_type="SPELLING", parameters=params, is_advisory=True)
    adapter = PySparkComputeAdapter()
    result = adapter.execute_rules(snapshot, [rule])[0]
    assert (result.counts.passed, result.counts.failed, result.counts.missing, result.counts.not_applicable) == (2, 1, 1, 1)
    base.with_suffix(".dic").write_bytes(b"1\nchanged\n")
    result = adapter.execute_rules(snapshot, [rule])[0]
    assert result.status.value == "FAILED_TO_MEASURE"


def test_json_regex_fault_is_isolated_from_valid_rule(tmp_path):
    source = tmp_path / "regex.jsonl"
    source.write_text('{"payload":{"code":"ABC","number":"10"}}\n{"payload":{"code":123,"number":10}}\n')
    snapshot = create_test_snapshot(source, file_format="JSONL")
    rules = [QualityRule(rule_id=uuid4(), rule_code=f"SYNTHETIC_{index}", dimension="VALIDITY", rule_type="JSON_FIELD", parameters={"column":"payload", **params}) for index, params in enumerate([
        {"path":"/code", "check":"REGEX", "pattern":"["},
        {"path":"/code", "check":"REGEX", "pattern":"^[A-Z]+$"},
        {"path":"/number", "check":"TYPE", "expected_type":"NUMBER"},
    ])]
    results = PySparkComputeAdapter().execute_rules(snapshot, rules)
    assert results[0].status.value == "FAILED_TO_MEASURE"
    assert (results[1].counts.passed, results[1].counts.miscast) == (1, 1)
    assert (results[2].counts.passed, results[2].counts.miscast) == (1, 1)
