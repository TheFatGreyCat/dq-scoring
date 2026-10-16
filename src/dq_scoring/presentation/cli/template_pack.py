"""CLI tool for validating and importing governed ruleset template packs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)
from pyspark.sql.window import Window

from dq_scoring.adapters.compute.spark_compute import _ensure_jdk_configured
from dq_scoring.adapters.compute.spelling_dictionary import SpellingDictionaryManager
from dq_scoring.adapters.compute.sql_rule_compiler import (
    CompiledRule,
    compile_rule,
    quoted_col,
)
from dq_scoring.core.entities import QualityRule
from dq_scoring.presentation.api.schemas.template_pack_schemas import (
    TemplatePack,
    bind_rules,
)

MAX_PACK_BYTES = 1024 * 1024


def _infer_schema(row: dict[str, Any]) -> StructType:
    fields = []
    for k, v in row.items():
        if v is None:
            t = StringType()
        elif isinstance(v, bool):
            t = BooleanType()
        elif isinstance(v, int):
            t = LongType()
        elif isinstance(v, float):
            t = DoubleType()
        elif isinstance(v, list):
            t = ArrayType(StringType())
        else:
            t = StringType()
        fields.append(StructField(k, t, True))
    return StructType(fields)


def _evaluate_row_outcome(cr: CompiledRule, df: DataFrame) -> str:
    eval_df = df
    if cr.is_uniqueness and cr.uniqueness_column:
        w = Window.partitionBy(quoted_col(cr.uniqueness_column)).orderBy(F.lit(1))
        col_name = f"_rn_{cr.rule_id.hex}"
        eval_df = eval_df.withColumn(col_name, F.row_number().over(w))
        is_failed = (~cr.missing_expr) & (F.col(col_name) > 1)
    else:
        is_failed = cr.failed_expr

    is_missing = cr.missing_expr
    is_miscast = cr.miscast_expr
    is_na = cr.scope_expr if cr.scope_expr is not None else F.lit(False)
    is_passed = (~is_na) & (~is_missing) & (~is_miscast) & (~is_failed)

    agg = eval_df.select(
        F.sum(F.when(is_na, 1).otherwise(0)).alias("na"),
        F.sum(F.when((~is_na) & is_missing, 1).otherwise(0)).alias("missing"),
        F.sum(F.when((~is_na) & (~is_missing) & is_miscast, 1).otherwise(0)).alias("miscast"),
        F.sum(F.when((~is_na) & (~is_missing) & (~is_miscast) & is_failed, 1).otherwise(0)).alias("failed"),
        F.sum(F.when(is_passed, 1).otherwise(0)).alias("passed"),
    ).collect()[0]

    if (agg["failed"] or 0) > 0:
        return "failed"
    if (agg["miscast"] or 0) > 0:
        return "miscast"
    if (agg["missing"] or 0) > 0:
        return "missing"
    if (agg["na"] or 0) > 0:
        return "not_applicable"
    if (agg["passed"] or 0) > 0:
        return "passed"
    return "unknown"


def validate_pack_file(file_path: Path) -> dict[str, Any]:
    if not file_path.is_file():
        raise FileNotFoundError(f"Template pack file not found: {file_path}")
    raw_bytes = file_path.read_bytes()
    if len(raw_bytes) > MAX_PACK_BYTES:
        raise ValueError(f"Template pack file exceeds limit of {MAX_PACK_BYTES} bytes")

    pack = TemplatePack.model_validate_json(raw_bytes)

    _ensure_jdk_configured()
    spark = (
        SparkSession.builder.master("local[1]")
        .appName("dq-template-pack-validator")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )

    spelling_manager = SpellingDictionaryManager()

    for template in pack.templates:
        for ex_idx, example in enumerate(template.examples):
            bound_rules = bind_rules(template.rules_payload, example.bindings)
            input_row = example.input
            schema = _infer_schema(input_row)

            for bound_dict in bound_rules:
                rule_code = bound_dict["rule_code"]
                expected_outcome = example.expected.get(rule_code)
                if not expected_outcome:
                    continue

                rule_type = bound_dict.get("rule_type", "NON_NULL")
                params = dict(bound_dict.get("parameters", {}))

                if rule_type == "SPELLING" and "dictionary_digests" not in params:
                    rev = params.get("dictionary_revision")
                    lang = params.get("language")
                    if rev and lang:
                        try:
                            params["dictionary_digests"] = spelling_manager.get_digests(rev, lang)
                        except (ValueError, OSError):
                            pass

                q_rule = QualityRule(
                    rule_id=uuid4(),
                    rule_code=rule_code,
                    dimension=bound_dict.get("dimension", "VALIDITY"),
                    rule_type=rule_type,
                    parameters=params,
                    null_policy=bound_dict.get("null_policy", "fail"),
                    is_advisory=bool(bound_dict.get("is_advisory", False)),
                )

                cr = compile_rule(q_rule)

                if cr.is_uniqueness and expected_outcome == "failed":
                    rows_data = [input_row, input_row]
                else:
                    rows_data = [input_row]

                df = spark.createDataFrame(rows_data, schema=schema)
                actual_outcome = _evaluate_row_outcome(cr, df)

                if actual_outcome != expected_outcome:
                    raise ValueError(
                        f"Template '{template.template_code}' example {ex_idx + 1} rule '{rule_code}': "
                        f"expected outcome '{expected_outcome}', got '{actual_outcome}'"
                    )

    return {
        "status": "VALID",
        "pack_code": pack.pack_code,
        "revision": pack.revision,
        "template_count": len(pack.templates),
    }


def import_pack_file(file_path: Path, api_url: str) -> dict[str, Any]:
    token = os.getenv("DQ_TEMPLATE_API_TOKEN")
    if not token or not token.strip():
        raise ValueError("DQ_TEMPLATE_API_TOKEN environment variable is required")

    if not file_path.is_file():
        raise FileNotFoundError(f"Template pack file not found: {file_path}")
    raw_bytes = file_path.read_bytes()
    if len(raw_bytes) > MAX_PACK_BYTES:
        raise ValueError(f"Template pack file exceeds limit of {MAX_PACK_BYTES} bytes")

    TemplatePack.model_validate_json(raw_bytes)

    base = api_url.rstrip("/")
    url = f"{base}/api/v1/templates/rulesets/import"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
    }

    response = httpx.post(url, content=raw_bytes, headers=headers, timeout=30.0)
    if response.status_code not in (200, 201):
        try:
            err = response.json()
        except (ValueError, json.JSONDecodeError):
            err = {"status_code": response.status_code, "text": response.text}
        raise RuntimeError(f"API import failed with status {response.status_code}: {err}")

    data = response.json()
    return {
        "status": "IMPORTED",
        "created": data.get("created", 0),
        "existing": data.get("existing", 0),
        "items_count": len(data.get("items", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DQ Scoring Template Pack CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    val_parser = subparsers.add_parser("validate", help="Validate a template pack structurally and behaviorally")
    val_parser.add_argument("--file", required=True, type=Path, help="Path to template pack JSON file")

    imp_parser = subparsers.add_parser("import", help="Import a template pack via API")
    imp_parser.add_argument("--file", required=True, type=Path, help="Path to template pack JSON file")
    imp_parser.add_argument("--api-url", required=True, type=str, help="Base URL of the DQ Scoring API")

    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            result = validate_pack_file(args.file)
            print(json.dumps(result, indent=2))
            return 0
        elif args.command == "import":
            result = import_pack_file(args.file, args.api_url)
            print(json.dumps(result, indent=2))
            return 0
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint format
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
