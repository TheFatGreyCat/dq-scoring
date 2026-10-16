"""Unit tests for privacy detectors, scanning accumulator, and masking."""
from __future__ import annotations

import pytest

from dq_scoring.common.privacy import (
    BUILTIN_DETECTOR_REVISION,
    PrivacyScanLimitExceededException,
    is_valid_luhn,
    mask_row,
    scan_rows,
)


def test_luhn_algorithm_boundaries():
    # Valid 16-digit Luhn card numbers
    assert is_valid_luhn("4532015112830366")
    assert is_valid_luhn("4532-0151-1283-0366")
    assert is_valid_luhn("4532 0151 1283 0366")
    # Invalid Luhn
    assert not is_valid_luhn("4532015112830367")
    assert not is_valid_luhn("1234567812345678")
    # Too short / too long (must be 13-19 digits)
    assert not is_valid_luhn("123456")
    assert not is_valid_luhn("123456789012345678901")


def test_scan_detects_email_and_preserves_plain_strings():
    rows = [
        {"id": "1", "contact": "user@example.com"},
        {"id": "2", "contact": "admin@sub.domain.vn"},
        {"id": "3", "contact": "not-an-email"},
        {"id": "4", "contact": None},
    ]
    summary = scan_rows(rows)
    assert summary["status"] == "COMPLETE"
    assert summary["detector_revision"] == BUILTIN_DETECTOR_REVISION
    assert summary["total_rows"] == 4
    assert "contact" in summary["sensitive_columns"]
    assert "id" not in summary["sensitive_columns"]

    findings = {f["detector_code"]: f for f in summary["findings"]}
    assert "EMAIL" in findings
    email_f = findings["EMAIL"]
    assert email_f["column_name"] == "contact"
    assert email_f["matched_count"] == 2
    assert email_f["observed_count"] == 3
    assert email_f["category"] == "BASIC_PERSONAL_DATA"
    assert email_f["method"] == "VALUE_PATTERN"


def test_scan_phone_does_not_treat_amount_or_arbitrary_numbers_as_phone():
    rows = [
        {"amount": "1000000", "txn_code": "0912345678", "phone": "0912345678"},
        {"amount": "5000000", "txn_code": "0987654321", "phone": "+84987654321"},
    ]
    summary = scan_rows(rows)
    # 'amount' must NOT be flagged as phone
    assert "amount" not in summary["sensitive_columns"]
    # 'phone' must be flagged as phone
    assert "phone" in summary["sensitive_columns"]


def test_scan_vn_id_only_in_id_columns():
    rows = [
        {"code": "012345678901", "cccd": "012345678901"},
        {"code": "098765432109", "cccd": "098765432109"},
    ]
    summary = scan_rows(rows)
    assert "code" not in summary["sensitive_columns"]
    assert "cccd" in summary["sensitive_columns"]
    vn_findings = [f for f in summary["findings"] if f["detector_code"] == "VN_ID"]
    assert len(vn_findings) == 1
    assert vn_findings[0]["column_name"] == "cccd"
    assert vn_findings[0]["category"] == "SENSITIVE_PERSONAL_DATA"


def test_scan_column_name_heuristics():
    rows = [
        {"full_name": "Nguyen Van A", "shipping_address": "123 Le Loi", "notes": "normal text"},
    ]
    summary = scan_rows(rows)
    assert "full_name" in summary["sensitive_columns"]
    assert "shipping_address" in summary["sensitive_columns"]
    assert "notes" not in summary["sensitive_columns"]

    methods = {f["detector_code"]: f["method"] for f in summary["findings"]}
    assert methods["PERSON_NAME"] == "COLUMN_NAME"
    assert methods["ADDRESS"] == "COLUMN_NAME"


def test_scan_nested_container_paths():
    rows = [
        {"id": "1", "payload": {"user": {"email": "alice@test.com"}}},
        {"id": "2", "payload": {"user": {"email": "bob@test.com"}}},
        {"id": "3", "payload": {"user": {"email": None}}},
    ]
    summary = scan_rows(rows)
    assert "payload" in summary["sensitive_columns"]
    findings = summary["findings"]
    assert len(findings) == 1
    f = findings[0]
    assert f["column_name"] == "payload"
    assert f["path"] == "/user/email"
    assert f["matched_count"] == 2
    assert f["observed_count"] == 2


def test_scan_distinct_paths_limit_exceeded():
    # Build a payload with >10000 distinct paths
    wide_dict = {f"k_{i}": i for i in range(10001)}
    with pytest.raises(PrivacyScanLimitExceededException):
        scan_rows([{"obj": wide_dict}])


def test_mask_row_full_mask():
    row = {
        "id": "100",
        "email": "alice@test.com",
        "nested": {"secret": "val"},
        "empty": "",
        "missing": None,
    }
    masked = mask_row(row, {"email", "nested", "empty", "missing"})
    assert masked["id"] == "100"
    assert masked["email"] == "[REDACTED]"
    assert masked["nested"] == "[REDACTED]"  # Whole container masked!
    assert masked["empty"] == ""
    assert masked["missing"] is None
