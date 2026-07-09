from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dq_core.runtime import DqRuntime, to_json


def main() -> None:
    parser = argparse.ArgumentParser(description="DQ Scoring V2 CLI")
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

    for name in ("profile_dataset", "recommend_rules", "save_recommended_bindings", "run_validation"):
        command = subparsers.add_parser(name)
        command.add_argument("--dataset-version-id", required=True)

    score = subparsers.add_parser("calculate_score")
    score.add_argument("--validation-run-id", required=True)
    score.add_argument("--scoring-policy-id")

    result = subparsers.add_parser("get_run_result")
    result.add_argument("--score-run-id")

    subparsers.add_parser("get_pipeline_logs")

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
        output = {"binding_run_id": runtime.save_recommended_rule_bindings(args.dataset_version_id)}
    elif args.command == "run_validation":
        output = {"validation_run_id": runtime.run_validation(args.dataset_version_id)}
    elif args.command == "calculate_score":
        output = {"score_run_id": runtime.calculate_score(args.validation_run_id, args.scoring_policy_id)}
    elif args.command == "get_run_result":
        output = runtime.get_run_result(args.score_run_id)
    elif args.command == "get_pipeline_logs":
        output = {"logs": runtime.get_pipeline_logs()}
    else:
        raise SystemExit(f"Unsupported command {args.command}")
    print(to_json(output))


if __name__ == "__main__":
    main()
