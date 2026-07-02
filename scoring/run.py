from __future__ import annotations

import argparse
import json
from pathlib import Path

from rules_engine.run import run_rules

from scoring.config import load_scoring_config
from scoring.engine import score_rules_engine_result
from scoring.store import DEFAULT_SCORE_STORE_PATH, ScoreStore


def run_scoring(
    dataset_config_path: str,
    rules_config_path: str,
    scoring_config_path: str,
    rules_store_path: str,
    score_store_path: str = str(DEFAULT_SCORE_STORE_PATH),
):
    rules_result = run_rules(dataset_config_path, rules_config_path, rules_store_path)
    scoring_config = load_scoring_config(scoring_config_path)
    scoring_result = score_rules_engine_result(rules_result, scoring_config, scoring_config_path)
    ScoreStore(score_store_path).store_scoring_result(scoring_result)
    return scoring_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 1 DQ Core Scoring")
    parser.add_argument("--dataset-config", required=True, help="Path to dataset config")
    parser.add_argument("--rules", required=True, help="Path to rule config YAML/JSON")
    parser.add_argument("--scoring-config", required=True, help="Path to scoring config YAML/JSON")
    parser.add_argument("--rules-store", required=True, help="SQLite rules store path")
    parser.add_argument("--score-store", default=str(DEFAULT_SCORE_STORE_PATH), help="SQLite score store path")
    parser.add_argument("--export-json", help="Optional path for Scoring Engine result JSON")
    args = parser.parse_args()

    result = run_scoring(
        args.dataset_config,
        args.rules,
        args.scoring_config,
        args.rules_store,
        args.score_store,
    )
    if args.export_json:
        export_path = Path(args.export_json)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(result.to_artifact(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.to_summary(args.score_store), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
