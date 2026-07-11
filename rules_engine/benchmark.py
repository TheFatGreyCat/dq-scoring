from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from profiling.column_profile import profile_columns
from profiling.models import DatasetConfig
from profiling.semantic_detection import detect_semantics
from rules_engine.catalog import default_rule_templates, recommend_rules


def calculate_metrics(results: list[dict[str, Any]], ground_truth: dict[str, dict[str, Any]], k: int = 3) -> dict[str, float]:
    by_column: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        column = str((item.get("target_columns") or [item.get("column_id") or ""])[0])
        by_column.setdefault(column, []).append(item)
    top1_hits = 0
    precision_hits = 0
    recall_hits = 0
    reciprocal_sum = 0.0
    wrong = 0
    returned_slots = 0
    ambiguous_expected = 0
    ambiguous_hit = 0
    evaluated = 0
    for column, truth in ground_truth.items():
        expected = set(truth.get("expected_rules") or [])
        forbidden = set(truth.get("forbidden_rules") or [])
        ranked = sorted(by_column.get(column, []), key=lambda item: item.get("rank") or 999)
        top_k = ranked[:k]
        top_codes = [str(item.get("rule_code") or item.get("rule_template_id")) for item in top_k]
        returned_slots += len(top_codes)
        if expected:
            if top_codes and top_codes[0] in expected:
                top1_hits += 1
            precision_hits += sum(1 for code in top_codes if code in expected)
            recall_hits += len(expected & set(top_codes))
            for rank, code in enumerate(top_codes, start=1):
                if code in expected:
                    reciprocal_sum += 1.0 / rank
                    break
        wrong += sum(1 for code in top_codes if code in forbidden)
        if truth.get("requires_review"):
            ambiguous_expected += 1
            if any(item.get("ambiguity_status") == "ambiguous" for item in top_k):
                ambiguous_hit += 1
        evaluated += 1
    denominator = max(evaluated, 1)
    expected_total = max(sum(len(item.get("expected_rules") or []) for item in ground_truth.values()), 1)
    return {
        "precision_at_1": round(top1_hits / denominator, 6),
        "precision_at_3": round(precision_hits / max(returned_slots, 1), 6),
        "recall_at_3": round(recall_hits / expected_total, 6),
        "mrr": round(reciprocal_sum / denominator, 6),
        "wrong_recommendation_rate": round(wrong / max(returned_slots, 1), 6),
        "ambiguous_column_detection_recall": round(ambiguous_hit / ambiguous_expected, 6) if ambiguous_expected else 1.0,
    }


def run_default_benchmark(report_path: str | Path = "docs/recommendation_benchmark_report.md") -> dict[str, Any]:
    results, ground_truth = _default_benchmark_inputs()
    metrics = calculate_metrics(results, ground_truth)
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_markdown(metrics, len(ground_truth)), encoding="utf-8")
    return {"metrics": metrics, "report_path": str(path)}


def _default_benchmark_inputs() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    frame = pd.DataFrame(
        {
            "customer_id": ["C001", "C002", "C003", "C004"],
            "email": ["a@example.com", "b@example.com", "c@example.com", "d@example.com"],
            "phone": ["0123456789", "0987654321", "0111222333", "0444555666"],
            "amount": ["10.5", "20", "0", "99.9"],
            "created_at": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        }
    )
    config = DatasetConfig(
        dataset_id="benchmark_customer_sales",
        dataset_name="Benchmark Customer Sales",
        dataset_type="customer_sales",
        source_type="csv",
        storage_path="memory.csv",
        primary_key=["customer_id"],
        mandatory_fields=["customer_id", "email", "amount"],
        cde_fields=["email", "amount", "created_at"],
        timestamp_column="created_at",
        declared_schema={"amount": {"data_type": "numeric"}, "created_at": {"data_type": "datetime"}},
    )
    profiles = profile_columns(frame, config, run_id="BENCHMARK")
    semantics = detect_semantics(profiles)
    templates = default_rule_templates()
    template_codes = {item.rule_template_id: item.rule_code for item in templates}
    recommendations = recommend_rules(profiles, semantics, config, templates, recommendation_run_id="BENCHMARK-RUN")
    results = [
        {
            "target_columns": item.target_columns,
            "rule_template_id": item.rule_template_id,
            "rule_code": template_codes.get(item.rule_template_id, item.rule_template_id),
            "rank": item.rank,
            "ambiguity_status": item.ambiguity_status,
        }
        for item in recommendations
    ]
    ground_truth = {
        "customer_id": {"expected_rules": ["IDENTIFIER_UNIQUE", "NOT_BLANK_MANDATORY", "NOT_NULL"], "forbidden_rules": ["ALLOWED_DOMAIN"], "requires_review": False},
        "email": {"expected_rules": ["EMAIL_FORMAT", "NOT_BLANK_MANDATORY", "NOT_NULL"], "forbidden_rules": ["PHONE_TEN_DIGITS"], "requires_review": False},
        "phone": {"expected_rules": ["PHONE_TEN_DIGITS", "STRING_LENGTH"], "forbidden_rules": ["EMAIL_FORMAT"], "requires_review": False},
        "amount": {"expected_rules": ["AMOUNT_NON_NEGATIVE", "NOT_BLANK_MANDATORY", "NOT_NULL"], "forbidden_rules": ["EMAIL_FORMAT"], "requires_review": True},
        "created_at": {"expected_rules": ["DATE_FORMAT", "DATETIME_NOT_FUTURE", "MIN_COMPLETENESS_RATIO"], "forbidden_rules": ["IDENTIFIER_UNIQUE"], "requires_review": False},
    }
    return results, ground_truth


def _markdown(metrics: dict[str, float], dataset_count: int = 0) -> str:
    rows = "\n".join(f"| {key} | {value} |" for key, value in metrics.items())
    return "# Recommendation Benchmark Report\n\n" f"Evaluated columns: {dataset_count}\n\n" "| Metric | Value |\n|---|---:|\n" + rows + "\n"


