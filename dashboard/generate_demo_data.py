from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring.run import run_scoring  # noqa: E402
from scoring.store import DEFAULT_SCORE_STORE_PATH  # noqa: E402
from rules_engine.store import DEFAULT_RULE_STORE_PATH  # noqa: E402


DATASETS = {
    "customer_master": {
        "dataset_config": "data/configs/customer_master.yaml",
        "rules": "data/rules/customer_master_rules.yaml",
        "scoring_config": "data/scoring/customer_master_scoring.yaml",
        "export_json": "customer_master_score.json",
    },
    "amazon_products": {
        "dataset_config": "data/configs/amazon.yaml",
        "rules": "data/rules/amazon_rules.yaml",
        "scoring_config": "data/scoring/amazon_scoring.yaml",
        "export_json": "amazon_products_score.json",
    },
    "retail_sales_dataset": {
        "dataset_config": "data/configs/retail_sales_dataset.yaml",
        "rules": "data/rules/retail_sales_dataset_rules.yaml",
        "scoring_config": "data/scoring/retail_sales_dataset_scoring.yaml",
        "export_json": "retail_sales_dataset_score.json",
    },
}


def generate_demo_data(
    datasets: Iterable[str],
    rules_store_path: str | Path = DEFAULT_RULE_STORE_PATH,
    score_store_path: str | Path = DEFAULT_SCORE_STORE_PATH,
    export_dir: str | Path = "data/score_store",
) -> list[dict[str, object]]:
    selected = _resolve_datasets(datasets)
    rules_store = Path(rules_store_path)
    score_store = Path(score_store_path)
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, object]] = []
    with _working_directory(ROOT):
        for dataset_id in selected:
            spec = DATASETS[dataset_id]
            result = run_scoring(
                spec["dataset_config"],
                spec["rules"],
                spec["scoring_config"],
                str(rules_store),
                str(score_store),
            )
            artifact_path = export_path / str(spec["export_json"])
            artifact_path.write_text(
                json.dumps(result.to_artifact(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary = result.to_summary(str(score_store))
            summary["export_json"] = str(artifact_path)
            summaries.append(summary)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo DQ Score data for Streamlit dashboard")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["all"],
        help="Dataset ids, comma-separated ids, or 'all'",
    )
    parser.add_argument("--rules-store", default=str(DEFAULT_RULE_STORE_PATH), help="Output SQLite rules store")
    parser.add_argument("--score-store", default=str(DEFAULT_SCORE_STORE_PATH), help="Output SQLite score store")
    parser.add_argument("--export-dir", default="data/score_store", help="Directory for JSON score artifacts")
    args = parser.parse_args()

    summaries = generate_demo_data(args.datasets, args.rules_store, args.score_store, args.export_dir)
    print(json.dumps({"runs": summaries}, ensure_ascii=False, indent=2))


def _resolve_datasets(values: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for value in values:
        expanded.extend(item.strip() for item in str(value).split(",") if item.strip())
    if not expanded or expanded == ["all"] or "all" in expanded:
        return list(DATASETS)
    unknown = [value for value in expanded if value not in DATASETS]
    if unknown:
        raise ValueError(f"Unknown dataset(s): {', '.join(unknown)}")
    return expanded


@contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


if __name__ == "__main__":
    main()
