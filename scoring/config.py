from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scoring.models import ScoringConfig


def load_scoring_config(path: str | Path) -> ScoringConfig:
    raw = _load_mapping(Path(path))
    return parse_scoring_config(raw)


def parse_scoring_config(raw: dict[str, Any]) -> ScoringConfig:
    dataset_type = str(raw.get("dataset_type", "default"))
    dimension_weights = raw.get("dimension_weights")
    if not isinstance(dimension_weights, dict) or not dimension_weights:
        raise ValueError("Scoring config must define non-empty dimension_weights")

    rule_weights = raw.get("rule_weights") or {}
    if not isinstance(rule_weights, dict):
        raise ValueError("Scoring config field rule_weights must be a mapping when provided")

    parsed_dimension_weights = {str(key): float(value) for key, value in dimension_weights.items()}
    total_weight = sum(parsed_dimension_weights.values())
    if total_weight <= 0:
        raise ValueError("Scoring config dimension_weights must sum to a positive value")

    return ScoringConfig(
        dataset_type=dataset_type,
        dimension_weights=parsed_dimension_weights,
        rule_weights={str(key): float(value) for key, value in rule_weights.items()},
        warning_margin=float(raw.get("warning_margin", 3.0)),
        quality_gate_pass_threshold=float(raw.get("quality_gate_pass_threshold", 80.0)),
        quality_gate_warning_threshold=float(raw.get("quality_gate_warning_threshold", 65.0)),
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
        raise ValueError("Scoring config file must contain a mapping object")
    return data


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        values: dict[str, Any] = {}
        while index < len(lines) and lines[index][0] == indent:
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

    if not lines:
        return {}
    parsed, next_index = parse_block(0, lines[0][0])
    if next_index != len(lines):
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

