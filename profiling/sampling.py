from __future__ import annotations

import pandas as pd

from profiling.models import DatasetConfig, SamplingInfo


def sample_dataset(df: pd.DataFrame, config: DatasetConfig) -> tuple[pd.DataFrame, SamplingInfo]:
    method = config.profiling_config.sampling_method
    total_rows = len(df)
    if method == "full_scan" or total_rows == 0:
        return df.copy(), SamplingInfo(method, False, None, total_rows, total_rows)
    if method != "random":
        raise NotImplementedError("Phase 1 MVP supports full_scan and random sampling")

    fraction = config.profiling_config.sample_fraction or 0.1
    fraction = max(0.0, min(1.0, fraction))
    min_sample_size = config.profiling_config.min_sample_size or 0
    sample_size = min(total_rows, max(int(total_rows * fraction), min_sample_size))
    sampled = df.sample(n=sample_size, random_state=config.profiling_config.random_seed)
    actual_fraction = sample_size / total_rows if total_rows else None
    return sampled.reset_index(drop=True), SamplingInfo(method, True, actual_fraction, sample_size, total_rows)
