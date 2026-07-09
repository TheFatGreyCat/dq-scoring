from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from dq_core.models import DatasetRuleBinding, RuleTemplate


GX_SUPPORTED_OPERATORS = {"not_null", "not_blank", "regex", "domain", "range", "length", "type_check", "uniqueness", "not_future"}
GX_RESULT_FORMAT = {
    "result_format": "SUMMARY",
    "partial_unexpected_count": 20,
    "return_unexpected_index_query": False,
    "include_unexpected_rows": False,
}


@dataclass(frozen=True)
class ExecutionStep:
    binding_id: str
    backend: str
    operator: str
    target_columns: list[str]
    parameters: dict[str, Any]


def ruleset_hash(bindings: list[DatasetRuleBinding], templates_by_id: dict[str, RuleTemplate], compiler_version: str = "v1") -> str:
    payload = []
    for binding in sorted(bindings, key=lambda item: item.binding_id):
        template = templates_by_id[binding.rule_template_id]
        payload.append(
            {
                "rule_template_id": binding.rule_template_id,
                "rule_template_version": template.rule_template_version,
                "target_columns": binding.target_columns,
                "parameters": {**template.parameters, **binding.parameters},
                "normalization_policy": template.normalization,
                "null_policy": template.null_policy,
                "acceptance_threshold": binding.acceptance_threshold,
                "backend": binding.backend,
                "compiler_version": compiler_version,
            }
        )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def plan_execution(bindings: list[DatasetRuleBinding], templates_by_id: dict[str, RuleTemplate]) -> list[ExecutionStep]:
    steps: list[ExecutionStep] = []
    for binding in bindings:
        template = templates_by_id[binding.rule_template_id]
        backend = binding.backend
        if backend in {"gx", "gx_pandas"} and template.operator not in GX_SUPPORTED_OPERATORS:
            backend = "python"
        steps.append(
            ExecutionStep(
                binding_id=binding.binding_id,
                backend=backend,
                operator=template.operator,
                target_columns=binding.target_columns,
                parameters={**template.parameters, **binding.parameters},
            )
        )
    return steps
