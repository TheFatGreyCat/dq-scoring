"""Utilities for CSV Formula Injection neutralization conforming to AC-025 and OWASP."""

from __future__ import annotations

from typing import Any

# Characters triggering spreadsheet dynamic formula execution
INJECTION_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell_value(value: Any) -> Any:
    """Neutralize potential CSV/spreadsheet formula injection by prepending single quote."""
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped and stripped.startswith(INJECTION_PREFIXES):
            return f"'{value}"
    return value


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Sanitize all string values within a single dictionary/row."""
    sanitized: dict[str, Any] = {}
    for key, val in record.items():
        if isinstance(val, dict):
            sanitized[key] = sanitize_record(val)
        elif isinstance(val, list):
            sanitized[key] = [sanitize_cell_value(item) for item in val]
        else:
            sanitized[key] = sanitize_cell_value(val)
    return sanitized


def sanitize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize a collection of tabular records prior to CSV serialization or export."""
    return [sanitize_record(r) for r in records]
