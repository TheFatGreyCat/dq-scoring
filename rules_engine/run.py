from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from profiling.config import load_config
from profiling.loading import load_dataset

from rules_engine.config import load_rules, validate_rule_config
from rules_engine.evaluators import RuleEvaluator, not_measured_result, skipped_result
from rules_engine.models import RuleRun, RulesEngineResult, iso
from rules_engine.store import DEFAULT_RULE_STORE_PATH, RuleStore


def run_rules(
    dataset_config_path: str,
    rules_config_path: str,
    store_path: str = str(DEFAULT_RULE_STORE_PATH),
) -> RulesEngineResult:
    dataset_config = load_config(dataset_config_path)
    rules = load_rules(rules_config_path)
    dataframe = load_dataset(dataset_config)
    columns = set(str(column) for column in dataframe.columns)
    rule_run_id = f"RRUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    evaluator = RuleEvaluator()

    evaluations = []
    samples = []
    for rule in rules:
        if rule.status != "active":
            evaluations.append(skipped_result(rule_run_id, rule, f"Rule status is '{rule.status}'"))
            continue
        errors = validate_rule_config(rule, dataset_config, columns)
        if errors:
            evaluations.append(not_measured_result(rule_run_id, rule, "; ".join(errors)))
            continue
        try:
            result, issue_samples = evaluator.evaluate_with_samples(dataframe, dataset_config, rule, rule_run_id)
            evaluations.append(result)
            samples.extend(issue_samples)
        except Exception as exc:
            evaluations.append(not_measured_result(rule_run_id, rule, str(exc)))

    measured = sum(1 for item in evaluations if item.measurement_status == "measured")
    not_measured = sum(1 for item in evaluations if item.measurement_status == "not_measured")
    skipped = sum(1 for item in evaluations if item.measurement_status == "skipped")
    status = "success" if not_measured == 0 else "partial_success"
    rule_run = RuleRun(
        rule_run_id=rule_run_id,
        dataset_id=dataset_config.dataset_id,
        dataset_version=None,
        run_timestamp=iso(datetime.now(timezone.utc)) or "",
        execution_engine="pandas",
        source_path=dataset_config.storage_path,
        rule_config_path=rules_config_path,
        status=status,
        total_rules=len(rules),
        measured_rules=measured,
        not_measured_rules=not_measured,
        skipped_rules=skipped,
    )
    result = RulesEngineResult(
        rule_run=rule_run,
        rule_configs=rules,
        rule_evaluation_results=evaluations,
        rule_issue_samples=samples,
    )
    RuleStore(store_path).store_rules_engine_result(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 1 DQ Rules Engine")
    parser.add_argument("--dataset-config", required=True, help="Path to dataset config")
    parser.add_argument("--rules", required=True, help="Path to rule config YAML/JSON")
    parser.add_argument("--store", default=str(DEFAULT_RULE_STORE_PATH), help="SQLite rules store path")
    parser.add_argument("--export-json", help="Optional path for normalized Rules Engine result JSON")
    args = parser.parse_args()
    result = run_rules(args.dataset_config, args.rules, args.store)
    if args.export_json:
        export_path = Path(args.export_json)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(result.to_artifact(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.to_summary(args.store), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
