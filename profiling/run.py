from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from profiling.anomaly_detection import detect_anomalies
from profiling.candidate_rules import generate_candidate_rules
from profiling.column_profile import profile_columns
from profiling.config import load_config
from profiling.dataset_profile import profile_dataset
from profiling.loading import load_dataset
from profiling.models import ProfileResult, ProfilingRun
from profiling.sampling import sample_dataset
from profiling.schema_profile import profile_schema
from profiling.store import DEFAULT_STORE_PATH, ProfileStore


def run_pipeline(config_path: str, store_path: str = str(DEFAULT_STORE_PATH)) -> ProfileResult:
    started_at = perf_counter()
    config = load_config(config_path)
    run_id = f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    store = ProfileStore(store_path)
    baseline = store.latest_baseline(config.dataset_id)

    df = load_dataset(config)
    profiled_df, sampling_info = sample_dataset(df, config)
    schema_profile = profile_schema(profiled_df, config)
    column_profiles = profile_columns(profiled_df, config, run_id=run_id)
    dataset_profile = profile_dataset(
        profiled_df,
        config,
        run_id=run_id,
        started_at=started_at,
        baseline=baseline,
    )
    candidate_rules = generate_candidate_rules(dataset_profile, column_profiles, config)
    anomaly_flags = detect_anomalies(dataset_profile, column_profiles, baseline, config)

    profiling_run = ProfilingRun(
        run_id=run_id,
        dataset_id=config.dataset_id,
        dataset_version=None,
        run_timestamp=dataset_profile.profiling_timestamp,
        execution_engine=config.profiling_config.execution_mode,
        source_path=config.storage_path,
        schema_version=None,
        sampling_method=sampling_info.sampling_method,
        is_sampled=sampling_info.is_sampled,
        sample_fraction=sampling_info.sample_fraction,
        sample_size=sampling_info.sample_size,
        total_rows=sampling_info.total_rows,
        status="success",
    )
    result = ProfileResult(
        profiling_run=profiling_run,
        schema_profile=schema_profile,
        dataset_profile=dataset_profile,
        column_profiles=column_profiles,
        candidate_rules=candidate_rules,
        anomaly_flags=anomaly_flags,
    )
    store.store_profile_result(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 1 DQ profiling pipeline")
    parser.add_argument("--config", required=True, help="Path to dataset profiling config")
    parser.add_argument("--store", default=str(DEFAULT_STORE_PATH), help="SQLite profile store path")
    parser.add_argument("--export-json", help="Optional path for normalized profile result JSON")
    args = parser.parse_args()
    result = run_pipeline(args.config, args.store)
    if args.export_json:
        export_path = Path(args.export_json)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(result.to_artifact(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.to_summary(args.store), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
