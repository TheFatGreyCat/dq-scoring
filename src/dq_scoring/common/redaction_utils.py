"""Utilities for PII redaction and evidence bounding conforming to DR-011 and SRS."""

from __future__ import annotations

import json
import re
from typing import Any

# Technical constants conforming to DR-011 and SRS Chapter 2
MAX_EVIDENCE_ROWS_PER_RESULT: int = 50
MAX_ASSESSMENT_EVIDENCE_BYTES: int = 500 * 1024  # 500 KB
MAX_RESULT_EVIDENCE_BYTES: int = 500 * 1024  # Under PostgreSQL 512,000 byte check constraint

# Standard compiled PII patterns
EMAIL_PATTERN: re.Pattern[str] = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
SSN_PATTERN: re.Pattern[str] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:\d{4}[-\s]?){3}\d{1,4}\b"
)
PHONE_PATTERN: re.Pattern[str] = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
# Column-name classes whose values cannot be found by pattern (matched as whole tokens)
NAME_COLUMN_TOKENS: frozenset[str] = frozenset(
    {"name", "firstname", "lastname", "fullname", "surname", "givenname", "middlename", "forename"}
)
ADDRESS_COLUMN_TOKENS: frozenset[str] = frozenset(
    {"address", "addr", "street", "postcode", "postal", "zip", "zipcode"}
)
_CAMEL_BOUNDARY: re.Pattern[str] = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_COLUMN_TOKEN: re.Pattern[str] = re.compile(r"[a-z0-9]+")


def redact_text(text: str) -> str:
    """Apply PII redaction rules to a string value."""
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = SSN_PATTERN.sub("[REDACTED_SSN]", text)
    text = CREDIT_CARD_PATTERN.sub("[REDACTED_CARD]", text)
    return PHONE_PATTERN.sub("[REDACTED_PHONE]", text)


def redact_value(value: Any) -> Any:
    """Recursively redact string values inside arbitrary nested structures."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def sensitive_column_marker(column: str) -> str | None:
    """Return a mask marker if the column name denotes a person name or address."""
    tokens = set(_COLUMN_TOKEN.findall(_CAMEL_BOUNDARY.sub("_", column).lower()))
    if tokens & NAME_COLUMN_TOKENS:
        return "[REDACTED_NAME]"
    if tokens & ADDRESS_COLUMN_TOKENS:
        return "[REDACTED_ADDRESS]"
    return None


def redact_sample_row(row: dict[str, Any]) -> dict[str, Any]:
    """Mask name/address columns whole (empty values stay visible); apply value-pattern redaction elsewhere."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        empty = value is None or (isinstance(value, str) and not value.strip())
        out[key] = value if empty else (sensitive_column_marker(str(key)) or redact_value(value))
    return out


def redact_evidence_samples(
    samples: list[dict[str, Any]] | None,
    max_rows: int = MAX_EVIDENCE_ROWS_PER_RESULT,
) -> list[dict[str, Any]]:
    """Cap sample count at max_rows and redact sensitive fields."""
    if not samples:
        return []
    bounded_samples = samples[:max_rows]
    return [redact_sample_row(row) for row in bounded_samples]


def prepare_bounded_evidence_payload(
    samples: list[dict[str, Any]] | None,
    error_message: str | None = None,
    max_rows: int = MAX_EVIDENCE_ROWS_PER_RESULT,
    max_bytes: int = MAX_RESULT_EVIDENCE_BYTES,
) -> dict[str, Any]:
    """Build a redacted, size-bounded evidence payload dict for a single result."""
    if max_bytes < 2:
        return {}

    payload: dict[str, Any] = {}
    if error_message:
        payload["error_message"] = redact_text(str(error_message))

    if samples:
        payload["evidence_samples"] = redact_evidence_samples(samples, max_rows=max_rows)

    def _encoded_size(p: dict[str, Any]) -> int:
        return len(json.dumps(p, ensure_ascii=False, default=str).encode("utf-8"))

    # Enforce per-result byte limit by progressively dropping sample rows
    if payload.get("evidence_samples"):
        while payload["evidence_samples"] and _encoded_size(payload) > max_bytes:
            payload["evidence_samples"].pop()
        if not payload["evidence_samples"]:
            payload.pop("evidence_samples", None)

    # If payload still exceeds max_bytes, truncate or remove error_message
    if _encoded_size(payload) > max_bytes and "error_message" in payload:
        suffix = "... [TRUNCATED]"
        suffix_size = len(
            json.dumps({"error_message": suffix}, ensure_ascii=False).encode("utf-8")
        )
        if suffix_size > max_bytes:
            payload.pop("error_message", None)
        else:
            avail = max(0, max_bytes - suffix_size)
            msg = payload["error_message"]
            for slice_len in range(min(len(msg), avail), -1, -5):
                payload["error_message"] = msg[:slice_len] + suffix
                if _encoded_size(payload) <= max_bytes:
                    break
            else:
                payload.pop("error_message", None)

    return payload
