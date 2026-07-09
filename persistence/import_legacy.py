from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from persistence.db import DEFAULT_DATASETS
from persistence.postgres import apply_migrations
from persistence.repository import DqPostgresRepository
from persistence.seed import build_seed_plan


def import_legacy(
    *,
    root: str | Path = ".",
    datasets: list[str] | None = None,
    dry_run: bool = False,
    reset: bool = False,
) -> dict[str, Any]:
    selected = datasets or DEFAULT_DATASETS
    plan = build_seed_plan(root, selected)
    report = _report(plan, selected)
    report["dry_run"] = dry_run
    if dry_run:
        return report

    apply_migrations()
    repository = DqPostgresRepository()
    if reset:
        repository.reset_v2_data()
    report["persisted"] = repository.save_seed_plan(plan)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy demo metadata into DQ Scoring V2 PostgreSQL contracts")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--dataset", action="append", dest="datasets", help="Dataset id to import; repeatable")
    parser.add_argument("--dry-run", action="store_true", help="Build and report import plan without writing")
    parser.add_argument("--reset", action="store_true", help="Reset V2 tables before importing")
    parser.add_argument("--report", help="Write import report JSON")
    args = parser.parse_args()

    report = import_legacy(root=args.root, datasets=args.datasets, dry_run=args.dry_run, reset=args.reset)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    print(output)


def _report(plan: dict[str, list[dict[str, Any]]], datasets: list[str]) -> dict[str, Any]:
    bindings = plan.get("dataset_rule_binding", [])
    templates = plan.get("rule_template", [])
    by_template = {template["rule_template_id"]: template for template in templates}
    review = [
        binding
        for binding in bindings
        if binding.get("source") == "review_required"
        or by_template.get(binding.get("rule_template_id"), {}).get("rule_category") in {"business", "technical"}
    ]
    return {
        "datasets_requested": datasets,
        "datasets_imported": len(plan.get("dataset", [])),
        "columns_imported": len(plan.get("dataset_column", [])),
        "templates_created": len(templates),
        "bindings_created": len(bindings),
        "rules_merged": max(0, len(bindings) - len(templates)),
        "rules_skipped": [],
        "rules_requiring_manual_review": [
            {
                "binding_id": item.get("binding_id"),
                "rule_template_id": item.get("rule_template_id"),
                "target_columns": item.get("target_columns", []),
            }
            for item in review
        ],
    }


if __name__ == "__main__":
    main()
