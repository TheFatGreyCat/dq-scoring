from __future__ import annotations

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
    raise SystemExit(
        "persistence.import_legacy is no longer a runtime command. "
        "Use python -m persistence.db migrate and register datasets through dq_core.cli or the dashboard."
    )

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


