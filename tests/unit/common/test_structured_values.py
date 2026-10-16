from decimal import Decimal

import pytest

from dq_scoring.common.structured_values import (
    StructuredParsingError,
    canonical_compact_json,
    evaluate_json_array,
    evaluate_json_field,
    extract_json_field,
    parse_structured_json,
)


def test_json_range_preserves_decimal_precision_and_partitions():
    params = {"path": "/amount", "check": "RANGE", "min": "0"}
    rows = ['{"amount":10}', '{"amount":-1}', '{}', None]
    assert [evaluate_json_field(row, params) for row in rows] == ["passed", "failed", "missing", "missing"]
    params["min"] = "1234567890.1234567890123456789"
    assert evaluate_json_field('{"amount":1234567890.1234567890123456788}', params) == "failed"
    assert evaluate_json_field('{"amount":true}', params) == "miscast"


def test_json_array_checks_numeric_equivalence_and_row_semantics():
    params = {"path": "/tags", "min_items": 1, "unique_items": True}
    rows = ['{"tags":["a","b"]}', '{"tags":["a","a"]}', '{"tags":[]}', None]
    assert [evaluate_json_array(row, params) for row in rows] == ["passed", "failed", "failed", "missing"]
    assert evaluate_json_array('{"tags":[1,1.0]}', params) == "failed"
    assert evaluate_json_array('{"tags":[{"a":1,"b":2},{"b":2,"a":1}]}', params) == "failed"


def test_parse_structured_json_valid_scalars_and_containers():
    data = '{"name": "Alice", "count": 42, "ratio": 12.34567890123456789, "active": true, "tags": ["a", "b"], "meta": {"k": "v"}}'
    parsed = parse_structured_json(data)
    assert parsed["name"] == "Alice"
    assert parsed["count"] == 42
    assert parsed["ratio"] == Decimal("12.34567890123456789")
    assert parsed["active"] is True
    assert parsed["tags"] == ["a", "b"]
    assert parsed["meta"] == {"k": "v"}


def test_parse_structured_json_rejects_duplicate_keys():
    bad = '{"a": 1, "a": 2}'
    with pytest.raises(StructuredParsingError) as exc_info:
        parse_structured_json(bad)
    assert exc_info.value.error_code == "DUPLICATE_KEY"


def test_parse_structured_json_rejects_constants():
    for bad in ('{"val": NaN}', '{"val": Infinity}', '{"val": -Infinity}'):
        with pytest.raises(StructuredParsingError) as exc_info:
            parse_structured_json(bad)
        assert exc_info.value.error_code in ("INVALID_JSON", "DISALLOWED_CONSTANT")


@pytest.mark.parametrize("text", ['"\\ud800"', '{"\\udfff":1}', '{"safe":"\\ud800"}'])
def test_escaped_lone_surrogates_are_rejected(text):
    with pytest.raises(StructuredParsingError) as error:
        parse_structured_json(text)
    assert error.value.error_code == "INVALID_ENCODING"


def test_duplicate_key_diagnostics_do_not_expose_keys():
    with pytest.raises(StructuredParsingError) as error:
        parse_structured_json('{"synthetic-private-key":1,"synthetic-private-key":2}')
    assert "synthetic-private-key" not in str(error.value)


def test_parse_structured_json_nesting_depth_limit():
    # Construct 32 levels of nesting - should pass
    cur: dict | list = "deep"
    for _ in range(31):
        cur = [cur]
    assert len(cur) == 1

    # Construct 33 levels of nesting - should fail with NESTING_TOO_DEEP
    deep: dict | list = "too_deep"
    for _ in range(33):
        deep = [deep]
    import json
    deep_json = json.dumps(deep)
    with pytest.raises(StructuredParsingError) as exc_info:
        parse_structured_json(deep_json)
    assert exc_info.value.error_code == "NESTING_TOO_DEEP"


def test_canonical_compact_json_sorting_and_formatting():
    obj = {"z": 1, "a": [2, 1], "m": {"b": True, "a": False}}
    encoded = canonical_compact_json(obj)
    # Sorted keys, compact separators
    assert encoded == '{"a":[2,1],"m":{"a":false,"b":true},"z":1}'

    # Decimals preserved
    dec_obj = {"amount": Decimal("100.50")}
    assert canonical_compact_json(dec_obj) == '{"amount":100.50}'

    # Primitives when passed to compact json
    assert canonical_compact_json("hello") == '"hello"'
    assert canonical_compact_json(True) == "true"
    assert canonical_compact_json(False) == "false"
    assert canonical_compact_json(123) == "123"
    assert canonical_compact_json(None) == "null"


def test_extract_json_field_rfc6901_paths():
    doc = {
        "user": {"name": "Alice", "tags": ["admin", "editor"], "ratio": Decimal("3.14")},
        "a/b": "slash_key",
        "m~n": "tilde_key",
        "empty_arr": [],
    }
    encoded = canonical_compact_json(doc)

    # Root path
    root_res = extract_json_field(encoded, "")
    assert root_res["state"] == "present"
    assert root_res["kind"] == "OBJECT"

    # Simple nested object
    name_res = extract_json_field(encoded, "/user/name")
    assert name_res["state"] == "present"
    assert name_res["kind"] == "STRING"
    assert name_res["text"] == "Alice"
    assert name_res["number_decimal"] is None

    # Number with Decimal
    num_res = extract_json_field(encoded, "/user/ratio")
    assert num_res["state"] == "present"
    assert num_res["kind"] == "NUMBER"
    assert num_res["text"] == "3.14"
    assert num_res["number_decimal"] == "3.14"

    # Array index
    tag0 = extract_json_field(encoded, "/user/tags/0")
    assert tag0["state"] == "present"
    assert tag0["kind"] == "STRING"
    assert tag0["text"] == "admin"

    # RFC 6901 escaped paths: ~1 for / and ~0 for ~
    slash_res = extract_json_field(encoded, "/a~1b")
    assert slash_res["state"] == "present"
    assert slash_res["text"] == "slash_key"

    tilde_res = extract_json_field(encoded, "/m~0n")
    assert tilde_res["state"] == "present"
    assert tilde_res["text"] == "tilde_key"

    # Missing path
    missing_key = extract_json_field(encoded, "/user/nonexistent")
    assert missing_key["state"] == "missing"

    missing_idx = extract_json_field(encoded, "/user/tags/99")
    assert missing_idx["state"] == "missing"

    # Scalar parent traversal -> miscast
    miscast_res = extract_json_field(encoded, "/user/name/sub")
    assert miscast_res["state"] == "miscast"

    # Null value
    doc_with_null = canonical_compact_json({"k": None})
    null_res = extract_json_field(doc_with_null, "/k")
    assert null_res["state"] == "missing"
    assert null_res["kind"] == "NULL"


def test_extract_json_field_malformed_input():
    # If the input is not valid JSON, extract_json_field returns miscast
    res = extract_json_field("not json", "/a")
    assert res["state"] == "miscast"

    # None input
    res_none = extract_json_field(None, "/a")
    assert res_none["state"] == "missing"
