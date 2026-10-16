"""Rule compiler translating QualityRule entities into vectorized Spark Column expressions.

Security invariant: user-supplied values (column names, formats, patterns, bounds) are
only ever passed to Spark as quoted identifiers or literals through the Column API.
No SQL text is assembled from rule parameters (no F.expr / selectExpr).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pyspark.sql import Column
from pyspark.sql import functions as F

from dq_scoring.core.entities import QualityRule

DEFAULT_TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss"
TEMPORAL_TYPES = frozenset({"TIMESTAMP", "DATETIME", "DATE"})
FLOATING_TYPES = frozenset({"DOUBLE", "FLOAT", "NUMERIC", "DECIMAL"})

_COMPARATORS = {
    ">=": Column.__ge__, "GTE": Column.__ge__,
    "<=": Column.__le__, "LTE": Column.__le__,
    ">": Column.__gt__, "GT": Column.__gt__,
    "<": Column.__lt__, "LT": Column.__lt__,
    "==": Column.__eq__, "=": Column.__eq__, "EQ": Column.__eq__,
    "!=": Column.__ne__, "<>": Column.__ne__, "NEQ": Column.__ne__,
}


@dataclass(frozen=True)
class CompiledRule:
    """Compiled Spark Column expressions representing mutually exclusive partitions."""

    rule_id: UUID
    target_column: str
    referenced_columns: tuple[str, ...]
    is_uniqueness: bool
    uniqueness_column: str | None
    scope_expr: Column | None
    missing_expr: Column
    miscast_expr: Column
    failed_expr: Column


def quoted_col(name: str) -> Column:
    """Reference a column by exact name; backticks are escaped so the name is never parsed."""
    return F.col("`" + name.replace("`", "``") + "`")


def _is_missing(col_name: str) -> Column:
    """Expression identifying null or whitespace-only empty string cells."""
    col = quoted_col(col_name)
    return col.isNull() | (F.trim(col) == "")


def _parse(col_name: str, data_type: str, fmt: str) -> Column:
    """Typed parse of a string column; NULL when the value does not parse."""
    col = quoted_col(col_name)
    if data_type in TEMPORAL_TYPES:
        temporal_fmt = "yyyy-MM-dd" if data_type == "DATE" and fmt == DEFAULT_TIMESTAMP_FORMAT else fmt
        return F.try_to_timestamp(col, F.lit(temporal_fmt))
    return col.try_cast("double" if data_type in FLOATING_TYPES else "bigint")


def _rule(
    rule: QualityRule,
    target_col: str,
    missing: Column,
    miscast: Column | None = None,
    failed: Column | None = None,
    extra_columns: tuple[str, ...] = (),
    uniqueness: bool = False,
) -> CompiledRule:
    return CompiledRule(
        rule_id=rule.rule_id,
        target_column=target_col,
        referenced_columns=(target_col, *extra_columns),
        is_uniqueness=uniqueness,
        uniqueness_column=target_col if uniqueness else None,
        scope_expr=None,
        missing_expr=missing,
        miscast_expr=miscast if miscast is not None else F.lit(False),
        failed_expr=failed if failed is not None else F.lit(False),
    )


def _compile_non_null(rule: QualityRule, target_col: str) -> CompiledRule:
    return _rule(rule, target_col, _is_missing(target_col))


def _compile_type_parse(rule: QualityRule, target_col: str) -> CompiledRule:
    data_type = str(rule.parameters.get("data_type") or rule.parameters.get("type", "DOUBLE")).upper()
    fmt = str(rule.parameters.get("format", DEFAULT_TIMESTAMP_FORMAT))
    missing = _is_missing(target_col)
    miscast = (~missing) & _parse(target_col, data_type, fmt).isNull()
    return _rule(rule, target_col, missing, miscast=miscast)


def _compile_domain_range(rule: QualityRule, target_col: str) -> CompiledRule:
    """DOMAIN_RANGE: allowed values, regex, calendar year, or numeric bounds (by parameter keys)."""
    params = rule.parameters
    missing = _is_missing(target_col)
    col = quoted_col(target_col)

    if "allowed_values" in params or "values" in params:
        values = list(params.get("allowed_values") or params.get("values", []))
        return _rule(rule, target_col, missing, failed=(~missing) & (~col.isin(values)))

    if "pattern" in params or "regex" in params:
        pattern = str(params.get("pattern") or params.get("regex", ""))
        return _rule(rule, target_col, missing, failed=(~missing) & (~col.rlike(pattern)))

    if "year" in params:
        year_val = int(params["year"])
        parsed_ts = _parse(target_col, "TIMESTAMP", str(params.get("format", DEFAULT_TIMESTAMP_FORMAT)))
        miscast = (~missing) & parsed_ts.isNull()
        failed = (~missing) & (~miscast) & (F.year(parsed_ts) != year_val)
        return _rule(rule, target_col, missing, miscast=miscast, failed=failed)

    min_val = params.get("min_value") if "min_value" in params else params.get("min")
    max_val = params.get("max_value") if "max_value" in params else params.get("max")
    num_val = _parse(target_col, "DOUBLE", DEFAULT_TIMESTAMP_FORMAT)
    miscast = (~missing) & num_val.isNull()
    failed_cond = F.lit(False)
    if min_val is not None:
        failed_cond = failed_cond | (num_val < float(min_val))
    if max_val is not None:
        failed_cond = failed_cond | (num_val > float(max_val))
    return _rule(rule, target_col, missing, miscast=miscast, failed=(~missing) & (~miscast) & failed_cond)


def _compile_cross_field(rule: QualityRule, target_col: str) -> CompiledRule:
    """CROSS_FIELD: compare target against another column with an allow-listed operator."""
    params = rule.parameters
    comp_col = params.get("comparison_column") or params.get("compare_to")
    if not comp_col:
        raise ValueError(f"CROSS_FIELD rule {rule.rule_code} missing comparison_column parameter")
    op = str(params.get("operator", ">="))
    comparator = _COMPARATORS.get(op.upper())
    if comparator is None:
        raise ValueError(f"CROSS_FIELD rule {rule.rule_code} has unsupported operator '{op}'")

    data_type = str(params.get("data_type") or "DOUBLE").upper()
    fmt = str(params.get("format", DEFAULT_TIMESTAMP_FORMAT))
    missing = _is_missing(target_col) | _is_missing(comp_col)
    parsed_a = _parse(target_col, "DOUBLE" if data_type not in TEMPORAL_TYPES else data_type, fmt)
    parsed_b = _parse(comp_col, "DOUBLE" if data_type not in TEMPORAL_TYPES else data_type, fmt)
    miscast = (~missing) & (parsed_a.isNull() | parsed_b.isNull())
    passes = comparator(parsed_a, parsed_b)
    return _rule(
        rule,
        target_col,
        missing,
        miscast=miscast,
        failed=(~missing) & (~miscast) & (~passes),
        extra_columns=(str(comp_col),),
    )


def _compile_uniqueness(rule: QualityRule, target_col: str) -> CompiledRule:
    return _rule(rule, target_col, _is_missing(target_col), uniqueness=True)


from dq_scoring.adapters.compute.text_rule_compiler import (
    compile_json_array,
    compile_json_field,
    compile_spelling,
    compile_text_quality,
)

_COMPILERS = {
    **dict.fromkeys(("NON_NULL", "NOT_NULL", "COMPLETENESS"), _compile_non_null),
    **dict.fromkeys(("TYPE_PARSE", "TYPE", "PARSER"), _compile_type_parse),
    **dict.fromkeys(("DOMAIN_RANGE", "RANGE", "DOMAIN", "ALLOWED_VALUES", "REGEX"), _compile_domain_range),
    **dict.fromkeys(("CROSS_FIELD", "CONSISTENCY", "COLUMN_COMPARISON"), _compile_cross_field),
    **dict.fromkeys(("UNIQUENESS", "UNIQUE", "DISTINCT"), _compile_uniqueness),
    "TEXT_QUALITY": compile_text_quality,
    "JSON_FIELD": compile_json_field,
    "JSON_ARRAY": compile_json_array,
    "SPELLING": compile_spelling,
}


def rule_target_column(rule: QualityRule) -> str | None:
    """Target column of a rule, from the entity or its parameters."""
    return (
        getattr(rule, "target_column", None)
        or rule.parameters.get("target_column")
        or rule.parameters.get("column")
    )


def compile_rule(rule: QualityRule) -> CompiledRule:
    """Compile a domain QualityRule into executable Spark Column expressions.

    Raises ValueError for an unknown rule type or invalid parameters; the caller records
    FAILED_TO_MEASURE for that rule only (rule fault containment).
    """
    target_col = rule_target_column(rule)
    if not target_col:
        raise ValueError(f"Rule {rule.rule_code} has no target column defined")
    compiler = _COMPILERS.get(rule.rule_type.upper())
    if compiler is None:
        raise ValueError(f"Rule {rule.rule_code} has unsupported rule type '{rule.rule_type}'")
    return compiler(rule, target_col)
