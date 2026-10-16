"""Unit tests for CSV formula injection sanitizer conforming to AC-025."""

from __future__ import annotations

from dq_scoring.common.formula_sanitizer import (
    sanitize_cell_value,
    sanitize_record,
    sanitize_records,
)


def test_sanitize_cell_value_formula_prefixes():
    """Verify dangerous formula prefixes are escaped with single quote."""
    assert sanitize_cell_value("=1+1") == "'=1+1"
    assert sanitize_cell_value("+cmd|'/c calc'!A1") == "'+cmd|'/c calc'!A1"
    assert sanitize_cell_value("-SUM(1,2)") == "'-SUM(1,2)"
    assert sanitize_cell_value("@SUM(1,2)") == "'@SUM(1,2)"
    assert sanitize_cell_value("\t=2+2") == "'\t=2+2"
    assert sanitize_cell_value("\r-5") == "'\r-5"


def test_sanitize_cell_value_safe_inputs():
    """Verify non-formula and non-string values are preserved without modification."""
    assert sanitize_cell_value("normal_text") == "normal_text"
    assert sanitize_cell_value("123.45") == "123.45"
    assert sanitize_cell_value(100) == 100
    assert sanitize_cell_value(42.5) == 42.5
    assert sanitize_cell_value(None) is None
    assert sanitize_cell_value(True) is True


def test_sanitize_nested_record():
    """Verify dictionary and nested structures are sanitized."""
    record = {
        "trip_id": "=1001",
        "fare": 15.5,
        "note": "-critical",
        "nested": {"command": "@execute"},
        "tags": ["=tag1", "safe_tag"],
    }
    sanitized = sanitize_record(record)
    assert sanitized["trip_id"] == "'=1001"
    assert sanitized["fare"] == 15.5
    assert sanitized["note"] == "'-critical"
    assert sanitized["nested"]["command"] == "'@execute"
    assert sanitized["tags"] == ["'=tag1", "safe_tag"]


def test_sanitize_records_collection():
    """Verify batch record sanitization."""
    records = [
        {"col_a": "=SUM(A1:A5)", "col_b": "clean"},
        {"col_a": "clean_2", "col_b": "+malicious"},
    ]
    sanitized = sanitize_records(records)
    assert sanitized[0]["col_a"] == "'=SUM(A1:A5)"
    assert sanitized[0]["col_b"] == "clean"
    assert sanitized[1]["col_a"] == "clean_2"
    assert sanitized[1]["col_b"] == "'+malicious"
