from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from profiling.models import DatasetConfig, ProfilingConfig


VALID_EXECUTION_MODES = {"gx_pandas", "gx_spark", "pyspark"}
VALID_SOURCE_TYPES = {"csv", "parquet", "excel", "json", "database", "datalake"}
VALID_SAMPLING_METHODS = {"full_scan", "random", "stratified"}
VALID_FRESHNESS_BASES = {"event_time", "updated_at", "ingestion_time"}


def load_config(path: str | Path) -> DatasetConfig:
    raw = _load_mapping(Path(path))
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> DatasetConfig:
    missing = [field for field in ("dataset_id", "source_type", "storage_path") if not raw.get(field)]
    if missing:
        raise ValueError(f"Missing required config field(s): {', '.join(missing)}")

    source_type = str(raw["source_type"]).lower()
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type '{source_type}'")

    profiling_raw = raw.get("profiling_config") or {}
    execution_mode = profiling_raw.get("execution_mode", "gx_pandas")
    sampling_method = profiling_raw.get("sampling_method", "full_scan")
    freshness_time_basis = raw.get("freshness_time_basis", "updated_at")

    if execution_mode not in VALID_EXECUTION_MODES:
        raise ValueError(f"Unsupported execution_mode '{execution_mode}'")
    if sampling_method not in VALID_SAMPLING_METHODS:
        raise ValueError(f"Unsupported sampling_method '{sampling_method}'")
    if freshness_time_basis not in VALID_FRESHNESS_BASES:
        raise ValueError(f"Unsupported freshness_time_basis '{freshness_time_basis}'")

    declared_schema = _normalize_schema(raw.get("declared_schema") or {})
    profiling_config = ProfilingConfig(
        execution_mode=execution_mode,
        sampling_method=sampling_method,
        sample_fraction=_optional_float(profiling_raw.get("sample_fraction")),
        min_sample_size=_optional_int(profiling_raw.get("min_sample_size")),
        random_seed=_optional_int(profiling_raw.get("random_seed")),
        enable_pattern_detection=bool(profiling_raw.get("enable_pattern_detection", True)),
        enable_candidate_rule_generation=bool(profiling_raw.get("enable_candidate_rule_generation", True)),
        enable_basic_anomaly_detection=bool(profiling_raw.get("enable_basic_anomaly_detection", True)),
        baseline_window=int(profiling_raw.get("baseline_window", 7)),
        thresholds=profiling_raw.get("thresholds") or {},
    )

    return DatasetConfig(
        dataset_id=str(raw["dataset_id"]),
        dataset_name=raw.get("dataset_name"),
        dataset_type=str(raw.get("dataset_type", "default")),
        source_type=source_type,
        storage_path=str(raw["storage_path"]),
        declared_schema=declared_schema,
        primary_key=_as_list(raw.get("primary_key")),
        composite_key=_as_list(raw.get("composite_key")),
        business_key=_as_list(raw.get("business_key")),
        mandatory_fields=_as_list(raw.get("mandatory_fields")),
        cde_fields=_as_list(raw.get("cde_fields")),
        timestamp_column=raw.get("timestamp_column"),
        freshness_time_basis=freshness_time_basis,
        sla_config=raw.get("sla_config") or {},
        profiling_config=profiling_config,
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        except ModuleNotFoundError:
            data = _parse_simple_yaml(text)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a mapping object")
    return data


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index
        is_list = lines[index][1].startswith("- ")
        if is_list:
            values = []
            while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
                item = lines[index][1][2:].strip()
                values.append(_parse_scalar(item))
                index += 1
            return values, index

        values: dict[str, Any] = {}
        while index < len(lines) and lines[index][0] == indent and not lines[index][1].startswith("- "):
            key, sep, value = lines[index][1].partition(":")
            if not sep:
                raise ValueError(f"Invalid YAML line: {lines[index][1]}")
            key = key.strip()
            value = value.strip()
            index += 1
            if value:
                values[key] = _parse_scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                values[key], index = parse_block(index, lines[index][0])
            else:
                values[key] = None
        return values, index

    parsed, next_index = parse_block(0, lines[0][0] if lines else 0)
    if next_index != len(lines) or not isinstance(parsed, dict):
        raise ValueError("Unsupported YAML structure; install PyYAML for full YAML support")
    return parsed


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _normalize_schema(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for name, spec in schema.items():
        if isinstance(spec, str):
            normalized[name] = {"data_type": spec}
        elif isinstance(spec, dict):
            normalized[name] = spec.copy()
        else:
            raise ValueError(f"Invalid declared_schema entry for '{name}'")
    return normalized


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
