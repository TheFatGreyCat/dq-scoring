"""Pure sensitive data detectors, scanning accumulator, and masking utilities."""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID, uuid5

from dq_scoring.common.privacy_rules import (
    BUILTIN_RULE_CATEGORIES,
    CompiledPrivacyRule,
    PrivacyDetectorRule,
    compile_rule,
)

BUILTIN_DETECTOR_REVISION = "builtin-v1"
MAX_DISTINCT_PATHS = 10_000
REDACTED_SENTINEL = "[REDACTED]"
SENSITIVE_CATEGORIES = frozenset({"BASIC_PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA", "CONFIDENTIAL_BUSINESS_DATA"})

# Dedicated namespace for deterministic finding IDs
FINDING_NAMESPACE = UUID("e812499d-1907-4e78-95f7-b86e7a2b2541")


class PrivacyScanLimitExceededException(Exception):
    """Raised when distinct finding paths exceed safety limits."""


# Regex patterns
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SSN_RE = re.compile(r"^(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}$")
_VN_PHONE_RE = re.compile(r"^(?:\+84|0)(?:[35789]\d{8}|2\d{9})$")
_E164_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_VN_ID_RE = re.compile(r"^\d{12}$")
_DIGITS_ONLY_RE = re.compile(r"^\d+$")

# Name heuristics
_NAME_MARKERS = (
    "name", "fullname", "full_name", "firstname", "first_name", "lastname", "last_name",
    "customername", "customer_name", "hoten", "ho_ten", "ten", "hovaten", "ho_va_ten",
    "sendername", "sender_name", "recipientname", "recipient_name", "beneficiaryname",
    "beneficiary_name", "clientname", "client_name", "employeename", "employee_name",
)

_ADDRESS_MARKERS = (
    "address", "street", "city", "postalcode", "postal_code", "zipcode", "zip_code",
    "diachi", "dia_chi", "billingaddress", "billing_address", "shippingaddress", "shipping_address",
)

_BANK_MARKERS = (
    "accountnumber", "account_number", "bankaccount", "bank_account", "sotaikhoan", "so_tai_khoan",
    "stk", "iban", "routingnumber", "routing_number", "swiftcode", "swift_code",
)

_SECRET_MARKERS = (
    "password", "passwd", "token", "secret", "apikey", "api_key", "privatekey", "private_key",
    "matkhau", "mat_khau",
)

_PHONE_COL_MARKERS = (
    "phone", "tel", "mobile", "dienthoai", "dien_thoai", "sdt", "so_dien_thoai",
)

_VN_ID_COL_MARKERS = (
    "cccd", "citizen_id", "national_id", "socccd", "so_cccd", "cmnd", "so_cmnd",
)


def is_valid_luhn(card_number: str) -> bool:
    """Validate numeric string using the Luhn checksum algorithm."""
    clean = re.sub(r"[\s-]", "", card_number)
    if not clean.isdigit() or not (13 <= len(clean) <= 19):
        return False
    digits = [int(d) for d in clean]
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = d * 2
            checksum += (doubled - 9) if doubled > 9 else doubled
        else:
            checksum += d
    return checksum % 10 == 0


def _normalize_identifier(name: str) -> str:
    return re.sub(r"[_\s-]", "", name).lower()


def _is_matching_marker(col_name: str, markers: tuple[str, ...]) -> bool:
    norm = _normalize_identifier(col_name)
    return any(norm == m or norm.endswith((f"_{m}", m)) for m in markers)


def generate_finding_id(
    snapshot_id: UUID,
    column_name: str,
    path: str,
    detector_code: str,
    detector_revision: str,
) -> UUID:
    key = f"{snapshot_id}\0{column_name}\0{path}\0{detector_code}\0{detector_revision}"
    return uuid5(FINDING_NAMESPACE, key)


_VALUE_CODES = ("EMAIL", "PHONE", "CARD", "SSN", "VN_ID")
_NAME_MARKERS_BY_CODE = {
    "PERSON_NAME": _NAME_MARKERS,
    "ADDRESS": _ADDRESS_MARKERS,
    "BANK_ACCOUNT": _BANK_MARKERS,
    "SECRET": _SECRET_MARKERS,
}


def _escape_pointer_key(key: Any) -> str:
    """RFC 6901 reference-token escaping."""
    return str(key).replace("~", "~0").replace("/", "~1")


class PrivacyScanner:
    """Streaming accumulator for privacy detection across dataset rows.

    `rules=None` runs the builtin detectors; an explicit sequence (even empty) is the complete detector set.
    """

    def __init__(
        self,
        columns: list[dict[str, Any]] | None = None,
        extra_columns: tuple[str, ...] = (),
        *,
        rules: Sequence[PrivacyDetectorRule] | None = None,
    ) -> None:
        self.sensitive_columns: set[str] = set(extra_columns)
        self.seen_paths: set[tuple[str, str]] = set()
        self.observed_counts: dict[tuple[str, str], int] = {}
        self.matched_counts: dict[tuple[str, str, str], int] = {}
        self.top_level_cols: set[str] = set()
        if columns:
            self.top_level_cols.update(c.get("name", "") for c in columns if c.get("name"))
        self.total_rows = 0

        # key is the rule_id, or the builtin code for default (rules=None) detectors.
        self._meta: dict[str, tuple[PrivacyDetectorRule | None, str, str, str]] = {}
        self._codes: dict[str, str] = {}
        self._builtins: dict[str, tuple[str, PrivacyDetectorRule | None]] = {}
        self._custom_value: list[tuple[str, CompiledPrivacyRule]] = []
        self._custom_name: list[tuple[str, CompiledPrivacyRule]] = []
        self._scoped_rules: list[PrivacyDetectorRule] = []
        if rules is None:
            for code, category in BUILTIN_RULE_CATEGORIES.items():
                self._register(code, None, category, _builtin_method(code), BUILTIN_DETECTOR_REVISION, code)
        for rule in rules or ():
            if not rule.enabled:
                continue
            key = str(rule.rule_id)
            if rule.columns:
                self._scoped_rules.append(rule)
            if rule.kind == "BUILTIN":
                code = rule.builtin_code or ""
                self._register(key, rule, rule.category, _builtin_method(code), BUILTIN_DETECTOR_REVISION, code)
            elif rule.kind == "COLUMN_NAME":
                self._register(key, rule, rule.category, "COLUMN_NAME", f"custom-v{rule.revision}", rule.code)
                self._custom_name.append((key, compile_rule(rule)))
            else:
                self._register(key, rule, rule.category, "CUSTOM_PATTERN", f"custom-v{rule.revision}", rule.code)
                self._custom_value.append((key, compile_rule(rule)))
        self._plans: dict[str, tuple[frozenset[str], tuple[tuple[str, CompiledPrivacyRule], ...]]] = {}

    def _register(
        self, key: str, rule: PrivacyDetectorRule | None, category: str, method: str, revision: str, code: str
    ) -> None:
        self._meta[key] = (rule, category, method, revision)
        self._codes[key] = code
        if rule is None or rule.kind == "BUILTIN":
            self._builtins[code] = (key, rule)

    def _plan(self, col: str) -> tuple[frozenset[str], tuple[tuple[str, CompiledPrivacyRule], ...]]:
        plan = self._plans.get(col)
        if plan is None:
            builtin_codes = frozenset(
                code for code in _VALUE_CODES
                if code in self._builtins and (self._builtins[code][1] is None or self._builtins[code][1].applies_to(col))
            )
            customs = tuple((key, rule) for key, rule in self._custom_value if rule.rule.applies_to(col))
            plan = self._plans[col] = (builtin_codes, customs)
        return plan

    def _hit(self, col: str, path: str, key: str) -> None:
        k = (col, path, key)
        self.matched_counts[k] = self.matched_counts.get(k, 0) + 1

    def _builtin_key(self, code: str) -> str:
        return self._builtins[code][0]

    def feed_row(self, row: dict[str, Any]) -> None:
        self.total_rows += 1
        self.top_level_cols.update(row.keys())

        for top_col, val in row.items():
            if val is None:
                continue

            builtin_codes, customs = self._plan(top_col)
            leaves: list[tuple[str, Any]] = []
            if isinstance(val, (dict, list)):
                stack: list[tuple[str, Any]] = [("", val)]
                while stack:
                    curr_path, curr_val = stack.pop()
                    if isinstance(curr_val, dict):
                        for k, sub_v in curr_val.items():
                            if sub_v is not None:
                                stack.append((f"{curr_path}/{_escape_pointer_key(k)}", sub_v))
                    elif isinstance(curr_val, list):
                        for item in curr_val:
                            if item is not None:
                                stack.append((f"{curr_path}/*", item))
                    else:
                        leaves.append((curr_path, curr_val))
            else:
                leaves.append(("", val))

            for path, leaf_val in leaves:
                path_key = (top_col, path)
                if path_key not in self.seen_paths:
                    if len(self.seen_paths) >= MAX_DISTINCT_PATHS:
                        raise PrivacyScanLimitExceededException(
                            f"Distinct finding paths exceeded limit of {MAX_DISTINCT_PATHS}"
                        )
                    self.seen_paths.add(path_key)

                self.observed_counts[path_key] = self.observed_counts.get(path_key, 0) + 1

                if isinstance(leaf_val, str):
                    for key, compiled in customs:
                        if compiled.matches(leaf_val):
                            self._hit(top_col, path, key)

                if builtin_codes:
                    self._scan_builtin_leaf(top_col, path, str(leaf_val).strip(), builtin_codes)

    def _scan_builtin_leaf(self, top_col: str, path: str, sval: str, codes: frozenset[str]) -> None:
        if not sval:
            return

        if "EMAIL" in codes and _EMAIL_RE.match(sval):
            self._hit(top_col, path, self._builtin_key("EMAIL"))

        if "PHONE" in codes and (_is_matching_marker(top_col, _PHONE_COL_MARKERS) or sval.startswith("+")):
            clean_phone = re.sub(r"[\s.-]", "", sval)
            if _VN_PHONE_RE.match(clean_phone) or _E164_PHONE_RE.match(clean_phone):
                self._hit(top_col, path, self._builtin_key("PHONE"))

        if "CARD" in codes:
            clean_digits = re.sub(r"[\s-]", "", sval)
            if 13 <= len(clean_digits) <= 19 and is_valid_luhn(clean_digits):
                self._hit(top_col, path, self._builtin_key("CARD"))

        if "SSN" in codes and _SSN_RE.match(sval):
            self._hit(top_col, path, self._builtin_key("SSN"))

        if "VN_ID" in codes and _is_matching_marker(top_col, _VN_ID_COL_MARKERS) and _VN_ID_RE.match(sval):
            self._hit(top_col, path, self._builtin_key("VN_ID"))

    def _mark_column_match(self, col: str, key: str) -> None:
        col_key = (col, "")
        obs = self.observed_counts.get(col_key, self.total_rows)
        self.matched_counts[(col, "", key)] = obs
        self.observed_counts[col_key] = obs

    def _scope_missing(self) -> list[dict[str, Any]]:
        summary = []
        for rule in self._scoped_rules:
            missing = sorted(set(rule.columns) - self.top_level_cols)
            if missing:
                summary.append({
                    "rule_id": str(rule.rule_id),
                    "rule_revision": rule.revision,
                    "detector_code": self._codes[str(rule.rule_id)],
                    "missing_columns": missing,
                })
        return sorted(summary, key=lambda item: (item["detector_code"], item["rule_id"]))

    def finish(self) -> dict[str, Any]:
        for col in self.top_level_cols:
            for code, markers in _NAME_MARKERS_BY_CODE.items():
                entry = self._builtins.get(code)
                if entry is None or (entry[1] is not None and not entry[1].applies_to(col)):
                    continue
                if _is_matching_marker(col, markers):
                    self._mark_column_match(col, entry[0])
            for key, compiled in self._custom_name:
                if compiled.rule.applies_to(col) and compiled.matches(col):
                    self._mark_column_match(col, key)

        findings: list[dict[str, Any]] = []
        for (col, path, key), matched in sorted(self.matched_counts.items()):
            if matched <= 0:
                continue
            self.sensitive_columns.add(col)
            rule, category, method, revision = self._meta[key]
            observed = self.observed_counts.get((col, path), matched)
            confidence = 1.0 if method == "COLUMN_NAME" else round(min(1.0, matched / max(1, observed)), 4)
            findings.append({
                "column_name": col,
                "path": path,
                "category": category,
                "detector_code": self._codes[key],
                "rule_id": str(rule.rule_id) if rule else None,
                "rule_revision": rule.revision if rule else None,
                "matched_count": matched,
                "observed_count": observed,
                "method": method,
                "detector_revision": revision,
                "confidence_score": confidence,
            })

        return {
            "status": "COMPLETE",
            "detector_revision": BUILTIN_DETECTOR_REVISION,
            "total_rows": self.total_rows,
            "findings": findings,
            "sensitive_columns": sorted(self.sensitive_columns),
            "scope_missing_columns": self._scope_missing(),
        }


def _builtin_method(code: str) -> str:
    return "COLUMN_NAME" if code in _NAME_MARKERS_BY_CODE else "VALUE_PATTERN"


def scan_rows(
    rows: Iterable[dict[str, Any]],
    columns: list[dict[str, Any]] | None = None,
    extra_columns: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Scan all rows for sensitive data patterns and column-level heuristics."""
    scanner = PrivacyScanner(columns=columns, extra_columns=extra_columns)
    for row in rows:
        scanner.feed_row(row)
    return scanner.finish()


def mask_row(row: dict[str, Any], sensitive_columns: set[str]) -> dict[str, Any]:
    """Pure FULL_MASK strategy: mask nonempty values of sensitive columns."""
    if not sensitive_columns:
        return dict(row)
    masked = {}
    for k, v in row.items():
        if k in sensitive_columns:
            if v is None:
                masked[k] = None
            elif v == "":
                masked[k] = ""
            else:
                masked[k] = REDACTED_SENTINEL
        else:
            masked[k] = v
    return masked
