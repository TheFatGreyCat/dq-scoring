"""Pinned privacy rules must match scalar leaves without exposing their values."""
from uuid import uuid4

from dq_scoring.common.privacy import PrivacyScanner
from dq_scoring.common.privacy_rules import PrivacyDetectorRule


def test_custom_search_matches_nested_scalar_and_escapes_pointer_keys():
    rule = PrivacyDetectorRule(
        rule_id=uuid4(), revision=1, code="SYNTHETIC_CODE", kind="VALUE_PATTERN",
        category="CONFIDENTIAL_BUSINESS_DATA", enabled=True, pattern=r"SYN-\d+",
        match_mode="SEARCH", case_sensitive=True, columns=("payload",),
    )
    scanner = PrivacyScanner(columns=[{"name": "payload"}], rules=[rule])
    scanner.feed_row({"payload": {"a/b~c": ["contact SYN-01 for testing", None, "ordinary"]}})
    result = scanner.finish()
    assert result["sensitive_columns"] == ["payload"]
    finding = result["findings"][0]
    assert finding["path"] == "/a~1b~0c/*"
    assert finding["matched_count"] == 1
    assert finding["observed_count"] == 2
    assert str(finding["rule_id"]) == str(rule.rule_id)
    assert finding["rule_revision"] == 1
    assert "contact SYN-01" not in str(result)


def test_explicit_empty_rules_does_not_fallback_to_builtins():
    scanner = PrivacyScanner(rules=[])
    scanner.feed_row({"email": "qa@example.com", "secret": "SYN-01"})
    result = scanner.finish()
    assert result["findings"] == []
    assert result["sensitive_columns"] == []
