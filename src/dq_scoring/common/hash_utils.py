"""Deterministic hash utilities for Assessments and Configurations."""

import hashlib
import json
from typing import Any


def compute_deterministic_hash(payload: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hex digest from dictionary payload.

    Invariants:
    - Sorted JSON keys
    - Compact separators (',', ':')
    - UTF-8 encoding
    """
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
