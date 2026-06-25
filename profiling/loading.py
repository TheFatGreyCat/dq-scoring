from __future__ import annotations

from pathlib import Path

import pandas as pd

from profiling.models import DatasetConfig


def load_dataset(config: DatasetConfig) -> pd.DataFrame:
    path = Path(config.storage_path)
    if config.source_type == "csv":
        return pd.read_csv(path, keep_default_na=False)
    if config.source_type == "parquet":
        return pd.read_parquet(path)
    raise NotImplementedError(
        f"source_type '{config.source_type}' is outside the Phase 1 MVP loader; "
        "add an adapter without changing profiling outputs."
    )
