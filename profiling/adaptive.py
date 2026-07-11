from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from profiling.models import DatasetConfig


@dataclass(frozen=True)
class ChunkedProfileSummary:
    row_count: int
    column_count: int
    null_counts: dict[str, int]
    blank_counts: dict[str, int]
    numeric_min: dict[str, float | None]
    numeric_max: dict[str, float | None]
    parse_ratio: dict[str, float]
    sample: pd.DataFrame = field(repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)


def profile_csv_in_chunks(path: str | Path, config: DatasetConfig) -> ChunkedProfileSummary:
    chunk_size = config.profiling_config.chunk_size
    random_seed = config.profiling_config.random_seed
    sample_rows: list[pd.DataFrame] = []
    row_count = 0
    null_counts: dict[str, int] = {}
    blank_counts: dict[str, int] = {}
    parse_success: dict[str, int] = {}
    non_empty_counts: dict[str, int] = {}
    numeric_min: dict[str, float | None] = {}
    numeric_max: dict[str, float | None] = {}
    columns: list[str] = []

    for chunk_index, chunk in enumerate(pd.read_csv(path, chunksize=chunk_size)):
        if not columns:
            columns = [str(column) for column in chunk.columns]
        row_count += len(chunk)
        if chunk_index == 0:
            sample_rows.append(chunk.head(100))
        sample_rows.append(chunk.sample(n=min(50, len(chunk)), random_state=(random_seed or 0) + chunk_index))
        for column in columns:
            series = chunk[column]
            null_counts[column] = null_counts.get(column, 0) + int(series.isna().sum())
            blanks = series.astype("string").str.strip().eq("").fillna(False)
            blank_counts[column] = blank_counts.get(column, 0) + int(blanks.sum())
            non_empty = series[~(series.isna() | blanks)]
            non_empty_counts[column] = non_empty_counts.get(column, 0) + len(non_empty)
            converted = pd.to_numeric(non_empty.astype(str).str.replace(",", "", regex=False), errors="coerce")
            parse_success[column] = parse_success.get(column, 0) + int(converted.notna().sum())
            valid = converted.dropna()
            if not valid.empty:
                current_min = float(valid.min())
                current_max = float(valid.max())
                numeric_min[column] = current_min if numeric_min.get(column) is None else min(float(numeric_min[column]), current_min)
                numeric_max[column] = current_max if numeric_max.get(column) is None else max(float(numeric_max[column]), current_max)
            else:
                numeric_min.setdefault(column, None)
                numeric_max.setdefault(column, None)

    sample = pd.concat(sample_rows).drop_duplicates().reset_index(drop=True) if sample_rows else pd.DataFrame(columns=columns)
    parse_ratio = {
        column: round(parse_success.get(column, 0) / non_empty_counts[column], 6) if non_empty_counts.get(column, 0) else 0.0
        for column in columns
    }
    return ChunkedProfileSummary(
        row_count=row_count,
        column_count=len(columns),
        null_counts=null_counts,
        blank_counts=blank_counts,
        numeric_min=numeric_min,
        numeric_max=numeric_max,
        parse_ratio=parse_ratio,
        sample=sample,
        metadata={
            "profile_strategy": "chunked_budget",
            "chunk_size": chunk_size,
            "memory_budget_mb": config.profiling_config.memory_budget_mb,
            "time_budget_sec": config.profiling_config.time_budget_sec,
            "sample_size": len(sample),
        },
    )