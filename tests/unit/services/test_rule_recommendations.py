from dq_scoring.services.rule_recommendations import recommend_rules


def test_selected_dimensions_numeric_boundary_and_identifier_disclaimer():
    schema = {"columns": [{"name": "transaction_id"}, {"name": "amount"}]}
    profile = {"sample_rows": 100, "columns": [
        {"name": "transaction_id", "type_hint": "STRING", "non_null_count": 100, "distinct_count": 100},
        {"name": "amount", "type_hint": "DOUBLE", "non_null_count": 100, "parse_success_count": 94},
    ]}
    result = recommend_rules(schema, profile, "FINANCE", ("VALIDITY", "UNIQUENESS"), [])
    assert [r["rule"]["rule_type"] for r in result["rules"]] == ["UNIQUENESS"]
    assert result["rules"][0]["reason_code"] == "SAMPLE_UNIQUENESS_NOT_PROOF"
    profile["columns"][1]["parse_success_count"] = 95
    result = recommend_rules(schema, profile, "FINANCE", ("VALIDITY",), [])
    assert result["rules"][0]["rule"]["parameters"] == {"column": "amount", "data_type": "DOUBLE"}
    assert result["rules"][0]["rule"]["is_required"] is False
    assert not any(r["rule"]["rule_type"] == "DOMAIN_RANGE" for r in result["rules"])
    assert recommend_rules(schema, profile, "FINANCE", (), [])["rules"] == []


def _full(columns):
    return {"mode": "FULL", "is_sample": False, "scanned_rows": 100, "total_rows": 100, "profile_id": "11111111-1111-1111-1111-111111111111",
            "fingerprint": "a" * 64, "columns": columns}


def test_full_profile_provenance_is_not_mislabeled_sample():
    schema = {"columns": [{"name": "amount"}]}
    profile = _full([{"name": "amount", "technical_type": "STRING", "null_count": 0, "non_null_count": 100,
                      "distinct_count": 5, "parse_success_count": 100, "parse_target": "DOUBLE", "parse_format": None}])
    result = recommend_rules(schema, profile, "FINANCE", ("COMPLETENESS", "VALIDITY"), [])
    assert {r["rule"]["rule_type"] for r in result["rules"]} == {"NON_NULL", "TYPE_PARSE"}
    for r in result["rules"]:
        assert r["is_sample"] is False and r["sample_rows"] == 100 and r["profile_mode"] == "FULL"
        assert r["profile_fingerprint"] == "a" * 64 and r["reason_code"].startswith("FULL_")
    assert result["warnings"] == ["FULL_RECOMMENDATIONS_REQUIRE_REVIEW"]


def test_unknown_parse_is_not_treated_as_success():
    schema = {"columns": [{"name": "amount"}]}
    profile = _full([{"name": "amount", "technical_type": "STRING", "null_count": 0, "non_null_count": 100,
                      "distinct_count": None, "parse_success_count": None, "parse_target": None, "parse_reason": "NO_EXPLICIT_TARGET"}])
    result = recommend_rules(schema, profile, "FINANCE", ("VALIDITY", "UNIQUENESS"), [])
    assert result["rules"] == []


def test_confirmed_label_decides_uniqueness_candidate_and_is_reported():
    schema = {"columns": [{"name": "ref"}, {"name": "customer_id"}]}
    profile = {"sample_rows": 100, "columns": [
        {"name": n, "type_hint": "STRING", "non_null_count": 100, "distinct_count": 100} for n in ("ref", "customer_id")]}
    plain = recommend_rules(schema, profile, "GENERAL", ("UNIQUENESS",), [])
    assert [r["rule"]["parameters"]["column"] for r in plain["rules"]] == ["customer_id"]
    confirmed = recommend_rules(schema, profile, "GENERAL", ("UNIQUENESS",), [], {"ref": "IDENTIFIER", "customer_id": "CATEGORY"})
    assert [(r["rule"]["parameters"]["column"], r["semantic"]) for r in confirmed["rules"]] == [("ref", "IDENTIFIER")]
