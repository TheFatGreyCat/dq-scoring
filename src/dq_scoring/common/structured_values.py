"""Structured value parsing, canonical JSON serialization, and RFC6901 JSON Pointer extraction."""

import json
from decimal import Decimal
from typing import Any


class StructuredParsingError(Exception):
    """Raised when JSON parsing encounters structural violations (duplicates, constants, excessive nesting)."""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def _reject_constants(raw: str) -> Any:
    raise StructuredParsingError("DISALLOWED_CONSTANT", f"JSON constant '{raw}' is disallowed")


def _check_depth(val: Any, current_depth: int = 1, max_depth: int = 32) -> None:
    if current_depth > max_depth:
        raise StructuredParsingError("NESTING_TOO_DEEP", f"Nesting depth exceeded maximum of {max_depth}")
    if isinstance(val, str):
        try:
            val.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise StructuredParsingError("INVALID_ENCODING", "Invalid Unicode surrogate") from exc
    elif isinstance(val, dict):
        for key, value in val.items():
            _check_depth(key, current_depth, max_depth)
            _check_depth(value, current_depth + isinstance(value, (dict, list)), max_depth)
    elif isinstance(val, list):
        for value in val:
            _check_depth(value, current_depth + isinstance(value, (dict, list)), max_depth)


def _object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for k, v in pairs:
        if k in obj:
            raise StructuredParsingError("DUPLICATE_KEY", "Duplicate JSON object key")
        obj[k] = v
    return obj


def parse_structured_json(text: str, max_depth: int = 32) -> Any:
    """Parse JSON text with strict validation: duplicate keys, no NaN/Infinity, depth limit."""
    if not isinstance(text, str):
        raise StructuredParsingError("INVALID_JSON", "Input must be a string")
    try:
        decoder = json.JSONDecoder(
            object_pairs_hook=_object_pairs_hook,
            parse_float=Decimal,
            parse_constant=_reject_constants,
        )
        # Verify valid surrogate handling
        text.encode("utf-8")
        parsed, idx = decoder.raw_decode(text.lstrip())
        remaining = text.lstrip()[idx:].strip()
        if remaining:
            raise StructuredParsingError("INVALID_JSON", "Trailing characters after JSON payload")
    except StructuredParsingError:
        raise
    except UnicodeEncodeError as exc:
        raise StructuredParsingError("INVALID_ENCODING", "Invalid Unicode surrogate") from exc
    except (ValueError, RecursionError) as exc:
        raise StructuredParsingError("INVALID_JSON", "Malformed JSON payload") from exc

    _check_depth(parsed, 1, max_depth)
    return parsed


def classify_value_kind(val: Any) -> str:
    """Classify logical kind for structured value."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "BOOLEAN"
    if isinstance(val, (int, float, Decimal)):
        return "NUMBER"
    if isinstance(val, str):
        return "STRING"
    if isinstance(val, dict):
        return "OBJECT"
    if isinstance(val, list):
        return "ARRAY"
    return "UNKNOWN"


def canonical_compact_json(val: Any) -> str:
    """Serialize value to compact canonical JSON with sorted object keys and exact numeric formatting."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, Decimal)):
        return str(val)
    if isinstance(val, float):
        # Convert via Decimal without scientific float notation surprises
        return str(Decimal(str(val)))
    if isinstance(val, str):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, dict):
        sorted_items = sorted(val.items(), key=lambda kv: kv[0])
        inner = ",".join(
            f"{json.dumps(k, ensure_ascii=False)}:{canonical_compact_json(v)}"
            for k, v in sorted_items
        )
        return f"{{{inner}}}"
    if isinstance(val, (list, tuple)):
        inner = ",".join(canonical_compact_json(v) for v in val)
        return f"[{inner}]"
    return json.dumps(str(val), ensure_ascii=False)


def decode_rfc6901_token(token: str) -> str:
    """Decode RFC6901 token (~1 -> /, ~0 -> ~)."""
    return token.replace("~1", "/").replace("~0", "~")


def extract_json_field(value: str | None, path: str) -> dict[str, Any]:
    """Extract field by RFC 6901 JSON Pointer path.

    Returns:
        {
            "state": "present" | "missing" | "miscast",
            "kind": "STRING" | "NUMBER" | "BOOLEAN" | "OBJECT" | "ARRAY" | "NULL" | None,
            "text": str | None,
            "number_decimal": str | None,
        }
    """
    if value is None:
        return {"state": "missing", "kind": None, "text": None, "number_decimal": None}

    try:
        root = parse_structured_json(value)
    except StructuredParsingError:
        return {"state": "miscast", "kind": None, "text": None, "number_decimal": None}

    # RFC 6901: empty string refers to whole document
    if path == "":
        target = root
    else:
        if not path.startswith("/"):
            return {"state": "miscast", "kind": None, "text": None, "number_decimal": None}
        tokens = [decode_rfc6901_token(part) for part in path[1:].split("/")]
        cur = root
        for tok in tokens:
            if isinstance(cur, dict):
                if tok not in cur:
                    return {"state": "missing", "kind": None, "text": None, "number_decimal": None}
                cur = cur[tok]
            elif isinstance(cur, list):
                try:
                    idx = int(tok)
                    if idx < 0 or idx >= len(cur):
                        return {"state": "missing", "kind": None, "text": None, "number_decimal": None}
                    cur = cur[idx]
                except ValueError:
                    return {"state": "missing", "kind": None, "text": None, "number_decimal": None}
            else:
                # Parent was a scalar, but another path segment was requested -> miscast
                return {"state": "miscast", "kind": None, "text": None, "number_decimal": None}
        target = cur

    if target is None:
        return {"state": "missing", "kind": "NULL", "text": None, "number_decimal": None}

    kind = classify_value_kind(target)
    if kind == "STRING":
        text = str(target)
        number_decimal = None
    elif kind == "NUMBER":
        text = str(target)
        number_decimal = str(target)
    elif kind == "BOOLEAN":
        text = "true" if target else "false"
        number_decimal = None
    elif kind in ("OBJECT", "ARRAY"):
        text = canonical_compact_json(target)
        number_decimal = None
    else:
        text = str(target)
        number_decimal = None

    return {
        "state": "present",
        "kind": kind,
        "text": text,
        "number_decimal": number_decimal,
    }


def evaluate_json_field(value: str | None, parameters: dict[str, Any]) -> str:
    field = extract_json_field(value, parameters["path"])
    if field["state"] != "present":
        return field["state"]
    check = parameters["check"]
    if check == "NON_NULL":
        return "passed"
    if check == "TYPE":
        return "passed" if field["kind"] == parameters["expected_type"] else "miscast"
    if check == "RANGE":
        if field["kind"] != "NUMBER":
            return "miscast"
        number = Decimal(field["number_decimal"])
        for bound, below in (("min", True), ("max", False)):
            if parameters.get(bound) is not None:
                limit = Decimal(parameters[bound])
                if (number < limit) if below else (number > limit):
                    return "failed"
        return "passed"
    if check == "ALLOWED_VALUES":
        if field["kind"] != "STRING":
            return "miscast"
        return "passed" if field["text"] in parameters["allowed_values"] else "failed"
    raise ValueError("JSON_FIELD check must be evaluated by the Spark regex compiler")


def _json_identity(value: Any) -> Any:
    kind = classify_value_kind(value)
    if kind == "NUMBER":
        return kind, Decimal(str(value))
    if kind == "OBJECT":
        return kind, tuple((key, _json_identity(item)) for key, item in sorted(value.items()))
    if kind == "ARRAY":
        return kind, tuple(_json_identity(item) for item in value)
    return kind, value


def evaluate_json_array(value: str | None, parameters: dict[str, Any]) -> str:
    field = extract_json_field(value, parameters["path"])
    if field["state"] != "present":
        return field["state"]
    if field["kind"] != "ARRAY":
        return "miscast"
    items = parse_structured_json(field["text"])
    if parameters.get("min_items") is not None and len(items) < parameters["min_items"]:
        return "failed"
    if parameters.get("max_items") is not None and len(items) > parameters["max_items"]:
        return "failed"
    if parameters.get("unique_items"):
        seen = set()
        for item in items:
            identity = _json_identity(item)
            if identity in seen:
                return "failed"
            seen.add(identity)
    return "passed"
