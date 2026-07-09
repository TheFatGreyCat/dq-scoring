from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dq_core.runtime import DqRuntime, to_json  # noqa: E402
from persistence.import_legacy import import_legacy  # noqa: E402
from persistence.repository import DqPostgresRepository  # noqa: E402


DATASETS = {
    "customer_master": "DV-customer_master-legacy",
    "amazon_products": "DV-amazon_products-legacy",
    "bank_transaction_fraud_detection": "DV-bank_transaction_fraud_detection-legacy",
    "retail_sales_dataset": "DV-retail_sales_dataset-legacy",
}


def generate_demo_data(datasets: Iterable[str], export_dir: str | Path = "data/score_store") -> list[dict[str, object]]:
    selected = _resolve_datasets(datasets)
    import_legacy(root=ROOT, datasets=selected, dry_run=False, reset=False)
    runtime = DqRuntime(DqPostgresRepository())
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, object]] = []
    for dataset_id in selected:
        dataset_version_id = DATASETS[dataset_id]
        profile_run_id = runtime.profile_dataset(dataset_version_id)
        validation_run_id = runtime.run_validation(dataset_version_id)
        score_run_id = runtime.calculate_score(validation_run_id)
        artifact = runtime.get_run_result(score_run_id)
        artifact_path = export_path / f"{dataset_id}_v2_score.json"
        artifact_path.write_text(to_json(artifact), encoding="utf-8")
        summaries.append(
            {
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "profiling_run_id": profile_run_id,
                "validation_run_id": validation_run_id,
                "score_run_id": score_run_id,
                "export_json": str(artifact_path),
            }
        )
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo DQ Score data")
    parser.add_argument("--datasets", nargs="+", default=["all"])
    parser.add_argument("--export-dir", default="data/score_store")
    args = parser.parse_args()
    print(json.dumps({"runs": generate_demo_data(args.datasets, args.export_dir)}, ensure_ascii=False, indent=2))


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


if __name__ == "__main__":
    main()
