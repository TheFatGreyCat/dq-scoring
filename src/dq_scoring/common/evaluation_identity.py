"""Stable identity of an evaluation request: what is scored, not who/when/which run id asked."""

from __future__ import annotations

from typing import Any

from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.core.entities import RunSpec

# Bump whenever scoring or normalization semantics change so older results are never reused.
EVALUATOR_VERSION = "raw-reader-v1"

_VOLATILE_SNAPSHOT_FIELDS = {"captured_at"}


def canonical_execution_profile(value: str | None) -> str:
    """'standard' and SPARK_K3S are the same engine; the column check only admits SPARK_K3S."""
    return "SPARK_K3S" if (value or "").upper() in ("", "SPARK_K3S", "STANDARD") else value  # type: ignore[return-value]


def evaluation_fingerprint(spec: RunSpec, *, profile_fingerprint: str) -> str:
    """SHA-256 over the evaluation inputs and the pinned FULL profile identity."""
    return compute_deterministic_hash(
        {
            "evaluator_version": EVALUATOR_VERSION,
            "tenant_id": spec.tenant_id,
            "snapshot": {
                key: value
                for key, value in spec.snapshot.model_dump(mode="json").items()
                if key not in _VOLATILE_SNAPSHOT_FIELDS
            },
            "ruleset_id": spec.ruleset_id,
            "rules": sorted((rule.model_dump(mode="json") for rule in spec.rules), key=lambda rule: rule["rule_id"]),
            "policy_id": spec.policy_id,
            "policy": spec.policy.model_dump(mode="json"),
            'profile_fingerprint': profile_fingerprint,
            "execution_profile": canonical_execution_profile(spec.execution_profile),
            "outlier_columns": list(spec.outlier_columns),
        }
    )


def request_fields_match(
    saved_spec: dict[str, Any],
    *,
    snapshot_id: Any,
    ruleset_id: Any,
    policy_id: Any,
    execution_profile: str | None,
    outlier_columns: list[str],
) -> bool:
    """Compare request semantics with a saved `_run_spec`; any missing saved field means no match."""
    snapshot = saved_spec.get("snapshot")
    saved_snapshot_id = snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None
    saved_outliers = saved_spec.get("outlier_columns")
    if None in (saved_snapshot_id, saved_spec.get('ruleset_id'), saved_spec.get('policy_id'), saved_spec.get('execution_profile')) or not isinstance(
        saved_outliers, list
    ):
        return False
    return (
        str(saved_snapshot_id) == str(snapshot_id)
        and str(saved_spec["ruleset_id"]) == str(ruleset_id)
        and str(saved_spec["policy_id"]) == str(policy_id)
        and canonical_execution_profile(saved_spec.get("execution_profile")) == canonical_execution_profile(execution_profile)
        and saved_outliers == list(outlier_columns)
    )


def request_identity_matches(saved_spec: dict[str, Any], requested: RunSpec) -> bool:
    """Same request semantics as a saved `_run_spec`; run/profile ids and reuse flags are not part of it."""
    return request_fields_match(
        saved_spec,
        snapshot_id=requested.snapshot.snapshot_id,
        ruleset_id=requested.ruleset_id,
        policy_id=requested.policy_id,
        execution_profile=requested.execution_profile,
        outlier_columns=requested.outlier_columns,
    )


def saved_run_matches(
    *,
    snapshot_id: Any,
    ruleset_id: Any,
    policy_id: Any,
    execution_profile: str | None,
    outlier_config: Any,
    requested: dict[str, Any],
) -> bool:
    """Compare a stored run row with request fields; legacy rows without `_run_spec` use only readable scalar fields."""
    saved = outlier_config.get("_run_spec") if isinstance(outlier_config, dict) else None
    if not isinstance(saved, dict):
        saved = {
            "snapshot": {"snapshot_id": snapshot_id},
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
            "execution_profile": execution_profile,
            "outlier_columns": outlier_config.get("outlier_columns") if isinstance(outlier_config, dict) else None,
        }
    return request_fields_match(saved, **requested)


def saved_request_matches(*, requested: RunSpec, **row: Any) -> bool:
    return saved_run_matches(
        requested={
            "snapshot_id": requested.snapshot.snapshot_id,
            "ruleset_id": requested.ruleset_id,
            "policy_id": requested.policy_id,
            "execution_profile": requested.execution_profile,
            "outlier_columns": requested.outlier_columns,
        },
        **row,
    )
