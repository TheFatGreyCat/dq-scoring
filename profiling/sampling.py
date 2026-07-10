from __future__ import annotations

from pathlib import Path

import pandas as pd

from profiling.models import DatasetConfig, SamplingInfo


FULL_SCAN_ROW_LIMIT = 100_000
FULL_SCAN_SIZE_LIMIT_BYTES = 100 * 1024 * 1024
WIDE_DATASET_COLUMN_LIMIT = 200
DEFAULT_SAMPLE_RATIO = 0.05
DEFAULT_MIN_SAMPLE_SIZE = 5_000
DEFAULT_MAX_SAMPLE_SIZE = 50_000
HEAD_TAIL_ROWS = 100


def sample_dataset(df: pd.DataFrame, config: DatasetConfig) -> tuple[pd.DataFrame, SamplingInfo]:
    method = config.profiling_config.sampling_method
    total_rows = len(df)
    if total_rows == 0:
        return df.copy(), _info(config, method, False, None, 0, 0, "full", None, 1.0, 1.0, [], "empty_dataset", "dataframe_full")

    scan_mode = _scan_mode(df, config)
    if method == "full_scan" or scan_mode == "full":
        return df.copy(), _info(config, method, False, None, total_rows, total_rows, "full", None, 1.0, 1.0, [], "completed", "dataframe_full")

    if method not in {"random", "auto", "adaptive", "mixed"}:
        raise NotImplementedError("Profiling supports full_scan, random, auto/adaptive, and mixed sampling")

    sample_ratio = config.profiling_config.sample_fraction or DEFAULT_SAMPLE_RATIO
    min_sample_size = config.profiling_config.min_sample_size or DEFAULT_MIN_SAMPLE_SIZE
    target_size = max(int(total_rows * sample_ratio), min_sample_size)
    target_size = min(total_rows, target_size, DEFAULT_MAX_SAMPLE_SIZE)
    sampled = _mixed_sample(df, target_size, config)
    actual_fraction = len(sampled) / total_rows if total_rows else None
    confidence = min(1.0, 0.60 + (actual_fraction or 0.0) * 4)
    return (
        sampled.reset_index(drop=True),
        _info(
            config,
            method,
            True,
            actual_fraction,
            len(sampled),
            total_rows,
            "sampled",
            _sample_method(config),
            actual_fraction,
            round(confidence, 6),
            _skipped_metrics(df, config),
            "completed",
            _profile_strategy(df, config),
        ),
    )


def _scan_mode(df: pd.DataFrame, config: DatasetConfig) -> str:
    method = config.profiling_config.sampling_method
    if method in {"random", "mixed"}:
        return "sampled"
    if method == "full_scan":
        return "full"
    if len(df) > FULL_SCAN_ROW_LIMIT:
        return "sampled"
    if len(df.columns) > WIDE_DATASET_COLUMN_LIMIT:
        return "sampled"
    try:
        path = Path(config.storage_path)
        if path.exists() and path.stat().st_size > FULL_SCAN_SIZE_LIMIT_BYTES:
            return "sampled"
    except OSError:
        pass
    return "full"


def _mixed_sample(df: pd.DataFrame, target_size: int, config: DatasetConfig) -> pd.DataFrame:
    if target_size >= len(df):
        return df.copy()
    head_size = min(HEAD_TAIL_ROWS, max(0, target_size // 10), len(df))
    tail_size = min(HEAD_TAIL_ROWS, max(0, target_size // 10), max(0, len(df) - head_size))
    head = df.head(head_size)
    tail = df.tail(tail_size) if tail_size else df.iloc[0:0]
    used = set(head.index) | set(tail.index)
    remaining = df.loc[~df.index.isin(used)]
    random_size = max(0, target_size - len(head) - len(tail))
    random = remaining.sample(n=min(random_size, len(remaining)), random_state=config.profiling_config.random_seed) if random_size and not remaining.empty else df.iloc[0:0]
    return pd.concat([head, tail, random]).loc[lambda frame: ~frame.index.duplicated(keep="first")]


def _null_heavy_sample(df: pd.DataFrame, size: int) -> pd.DataFrame:
    if size <= 0 or df.empty:
        return df.iloc[0:0]
    score = df.isna().sum(axis=1) + df.astype("string").apply(lambda col: col.str.strip().eq("").fillna(False)).sum(axis=1)
    return df.loc[score.sort_values(ascending=False).head(size).index]


def _duplicate_sample(df: pd.DataFrame, size: int) -> pd.DataFrame:
    if size <= 0 or df.empty:
        return df.iloc[0:0]
    row_hash = pd.util.hash_pandas_object(df.astype("string"), index=False)
    duplicated = row_hash.duplicated(keep=False)
    return df.loc[duplicated[duplicated].head(size).index]


def _sample_method(config: DatasetConfig) -> str:
    parts = ["head", "tail", "random"]
    if config.profiling_config.enable_null_heavy_sampling:
        parts.append("null_heavy")
    if config.profiling_config.enable_duplicate_aware_sampling:
        parts.append("duplicate_aware")
    return "mixed_" + "_".join(parts)


def _profile_strategy(df: pd.DataFrame, config: DatasetConfig) -> str:
    if len(df.columns) > WIDE_DATASET_COLUMN_LIMIT:
        return "wide_lightweight_selective_deep"
    estimated_mb = float(df.memory_usage(deep=True).sum()) / (1024 * 1024)
    if estimated_mb > config.profiling_config.memory_budget_mb:
        return "chunked_budget"
    return "dataframe_sampled" if _scan_mode(df, config) == "sampled" else "dataframe_full"


def _skipped_metrics(df: pd.DataFrame, config: DatasetConfig) -> list[str]:
    skipped: list[str] = []
    if len(df.columns) > config.profiling_config.max_deep_columns:
        skipped.append("deep_profile_all_columns")
    estimated_mb = float(df.memory_usage(deep=True).sum()) / (1024 * 1024)
    if estimated_mb > config.profiling_config.memory_budget_mb:
        skipped.append("full_dataframe_deep_metrics")
    return skipped


def _info(
    config: DatasetConfig,
    method: str,
    is_sampled: bool,
    sample_fraction: float | None,
    sample_size: int,
    total_rows: int,
    scan_mode: str,
    sample_method: str | None,
    coverage: float | None,
    confidence: float | None,
    skipped_metrics: list[str],
    termination_reason: str,
    profile_strategy: str,
) -> SamplingInfo:
    return SamplingInfo(
        method,
        is_sampled,
        sample_fraction,
        sample_size,
        total_rows,
        scan_mode=scan_mode,
        sample_method=sample_method,
        random_seed=config.profiling_config.random_seed,
        coverage_estimate=coverage,
        profile_confidence=confidence,
        chunk_size=config.profiling_config.chunk_size,
        memory_budget_mb=config.profiling_config.memory_budget_mb,
        time_budget_sec=config.profiling_config.time_budget_sec,
        budget_used={"estimated_memory_mb": None},
        skipped_metrics=skipped_metrics,
        termination_reason=termination_reason,
        deep_profiled_columns=[],
        profile_strategy=profile_strategy,
    )
