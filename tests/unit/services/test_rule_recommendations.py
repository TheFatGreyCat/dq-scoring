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
