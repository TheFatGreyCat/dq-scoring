"""Unit tests for PII redaction and bounded evidence utilities."""

from __future__ import annotations

from dq_scoring.common.redaction_utils import (
    MAX_EVIDENCE_ROWS_PER_RESULT,
    prepare_bounded_evidence_payload,
    redact_evidence_samples,
    redact_text,
    redact_value,
)


def test_redact_text_pii_patterns() -> None:
    text = (
        "Contact alice@example.com, phone +1 (555) 123-4567, "
        "SSN 123-45-6789 and Card 4111-2222-3333-4444."
    )
    redacted = redact_text(text)
    assert "alice@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "123-45-6789" not in redacted
    assert "[REDACTED_SSN]" in redacted
    assert "4111-2222-3333-4444" not in redacted
    assert "[REDACTED_CARD]" in redacted
    assert "(555) 123-4567" not in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_redact_value_recursive() -> None:
    nested = {
        "user": {
            "email": "bob@domain.org",
            "phones": ["123-456-7890", "555-555-5555"],
        },
        "score": 98.5,
        "is_valid": True,
    }
    redacted = redact_value(nested)
    assert redacted["user"]["email"] == "[REDACTED_EMAIL]"
    assert redacted["user"]["phones"] == ["[REDACTED_PHONE]", "[REDACTED_PHONE]"]
    assert redacted["score"] == 98.5
    assert redacted["is_valid"] is True


def test_redact_evidence_samples_row_cap() -> None:
    # Generate 80 sample rows with sensitive emails
    raw_samples = [
        {"row_id": i, "email": f"user{i}@company.com", "val": -10}
        for i in range(80)
    ]
    bounded = redact_evidence_samples(raw_samples)
    assert len(bounded) == MAX_EVIDENCE_ROWS_PER_RESULT
    assert len(bounded) == 50
    assert bounded[0]["email"] == "[REDACTED_EMAIL]"
    assert bounded[49]["row_id"] == 49


def test_prepare_bounded_evidence_payload_byte_limit() -> None:
    # Generate samples that exceed a small byte budget
    samples = [{"idx": i, "details": "x" * 200} for i in range(40)]
    payload = prepare_bounded_evidence_payload(
        samples=samples,
        error_message="Test error message",
        max_bytes=1000,
    )
    # Samples should be pruned to fit within 1000 bytes
    assert len(payload["evidence_samples"]) < 40
    assert "error_message" in payload

def test_prepare_bounded_evidence_payload_zero_and_minimal_budget() -> None:
    samples = [{"idx": 1, "val": "abc"}]
    # 0 or 1 byte budget must return empty dict
    assert prepare_bounded_evidence_payload(samples=samples, max_bytes=0) == {}
    assert prepare_bounded_evidence_payload(samples=samples, max_bytes=1) == {}

    # Small budget with large error message
    huge_msg = "Critical error " * 50
    payload = prepare_bounded_evidence_payload(
        samples=samples, error_message=huge_msg, max_bytes=50
    )
    import json
    encoded_len = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert encoded_len <= 50


def test_name_columns_are_masked() -> None:
    [row] = redact_evidence_samples([{"first_name": "Alice", "LastName": "Nguyen", "customerName": "Bob", "fare": -1.0}])
    assert row == {"first_name": "[REDACTED_NAME]", "LastName": "[REDACTED_NAME]", "customerName": "[REDACTED_NAME]", "fare": -1.0}


def test_address_columns_are_masked_including_non_strings() -> None:
    [row] = redact_evidence_samples([{"billing_address": "12 Main St", "addressLine1": "Apt 4", "zip_code": "60601", "street": 5}])
    assert set(row.values()) == {"[REDACTED_ADDRESS]"}


def test_null_values_in_sensitive_columns_stay_null() -> None:
    assert redact_evidence_samples([{"full_name": None, "address": None}]) == [{"full_name": None, "address": None}]


def test_lookalike_columns_are_not_masked() -> None:
    row = {"renamed": "x", "filename": "a.csv", "zipper_count": 3, "company": "Flash Cab"}
    assert redact_evidence_samples([row]) == [row]


def test_value_patterns_still_apply_to_other_columns() -> None:
    [row] = redact_evidence_samples([{"contact": "alice@example.com"}])
    assert row == {"contact": "[REDACTED_EMAIL]"}


def test_bounded_payload_masks_names() -> None:
    payload = prepare_bounded_evidence_payload([{"driver_name": "Carol"}])
    assert payload["evidence_samples"] == [{"driver_name": "[REDACTED_NAME]"}]


def test_empty_strings_in_sensitive_columns_stay_empty() -> None:
    assert redact_evidence_samples([{"full_name": "", "address": "  "}]) == [{"full_name": "", "address": "  "}]
