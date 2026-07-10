from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dq_core.health import get_system_health
from dq_core.runtime import DqRuntime, to_json


def main() -> None:
    parser = argparse.ArgumentParser(description="DQ Scoring CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register_dataset")
    register.add_argument("--csv", required=True)
    register.add_argument("--dataset-id", required=True)
    register.add_argument("--dataset-name")
    register.add_argument("--dataset-type", default="default")
    register.add_argument("--primary-key", action="append", default=[])
    register.add_argument("--business-key", action="append", default=[])
    register.add_argument("--mandatory-field", action="append", default=[])
    register.add_argument("--cde-field", action="append", default=[])
    register.add_argument("--timestamp-column")

    for name in ("profile_dataset", "recommend_rules", "run_validation"):
        command = subparsers.add_parser(name)
        command.add_argument("--dataset-version-id", required=True)

    bindings = subparsers.add_parser("save_recommended_bindings", description="Bind accepted/edited recommendations; optionally auto-bind safe high-confidence recommendations.")
    bindings.add_argument("--dataset-version-id", required=True)
    bindings.add_argument("--accept-all-above-threshold", action="store_true")
    bindings.add_argument("--threshold", type=float, default=0.85)

    review = subparsers.add_parser("review_recommendation")
    review.add_argument("--recommendation-id", required=True)
    review.add_argument("--decision", required=True, choices=["suggested", "accepted", "rejected", "edited"])
    review.add_argument("--parameters-json")

    score = subparsers.add_parser("calculate_score")
    score.add_argument("--validation-run-id", required=True)
    score.add_argument("--scoring-policy-id")

    result = subparsers.add_parser("get_run_result")
    result.add_argument("--score-run-id")

    subparsers.add_parser("get_pipeline_logs")
    subparsers.add_parser("health_check")
    subparsers.add_parser("bootstrap_catalog")
    subparsers.add_parser("catalog_inventory")
    subparsers.add_parser("benchmark_recommendations")

    args = parser.parse_args()
    runtime = DqRuntime()
    output: Any
    if args.command == "register_dataset":
        metadata = {
            "dataset_id": args.dataset_id,
            "dataset_name": args.dataset_name,
            "dataset_type": args.dataset_type,
            "primary_key": args.primary_key,
            "business_key": args.business_key,
            "mandatory_fields": args.mandatory_field,
            "cde_fields": args.cde_field,
            "timestamp_column": args.timestamp_column,
            "storage_path": str(Path(args.csv)),
        }
        output = {"dataset_version_id": runtime.register_dataset(args.csv, metadata)}
    elif args.command == "profile_dataset":
        output = {"profiling_run_id": runtime.profile_dataset(args.dataset_version_id)}
    elif args.command == "recommend_rules":
        output = {"recommendations": runtime.recommend_rules(args.dataset_version_id)}
    elif args.command == "save_recommended_bindings":
        output = {
            "binding_run_id": runtime.save_recommended_rule_bindings(
                args.dataset_version_id,
                accept_all_above_threshold=args.accept_all_above_threshold,
                threshold=args.threshold,
            )
        }
    elif args.command == "run_validation":
        output = {"validation_run_id": runtime.run_validation(args.dataset_version_id)}
    elif args.command == "calculate_score":
        output = {"score_run_id": runtime.calculate_score(args.validation_run_id, args.scoring_policy_id)}
    elif args.command == "get_run_result":
        output = runtime.get_run_result(args.score_run_id)
    elif args.command == "get_pipeline_logs":
        output = {"logs": runtime.get_pipeline_logs()}
    elif args.command == "health_check":
        output = get_system_health()
    elif args.command == "bootstrap_catalog":
        output = runtime.bootstrap_catalog()
    elif args.command == "catalog_inventory":
        output = runtime.catalog_inventory()
    elif args.command == "review_recommendation":
        parameters = json.loads(args.parameters_json) if args.parameters_json else None
        output = runtime.review_recommendation(args.recommendation_id, args.decision, parameters)
    elif args.command == "benchmark_recommendations":
        from rules_engine.benchmark import run_default_benchmark

        output = run_default_benchmark()
    else:
        raise SystemExit(f"Unsupported command {args.command}")
    print(to_json(output))


if __name__ == "__main__":
    main()
