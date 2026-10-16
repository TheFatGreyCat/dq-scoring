"""Map persisted scoring_policies rows onto the domain ScoringPolicy."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from dq_scoring.core.models import ScoringPolicy


def scoring_policy_from_row(
    policy_id: UUID,
    dimension_weights: dict[str, float] | None,
    publication_threshold: float,
    gate_rules: dict[str, Any] | None,
) -> ScoringPolicy:
    """Build the domain policy from a scoring_policies row.

    gate_rules uses the API keys (gate_fail_threshold / gate_warn_threshold); the legacy
    warn_min / pass_min keys are still read for rows written before that convention.
    Missing keys fall back to the ScoringPolicy defaults, never to ad-hoc literals.
    """
    rules = gate_rules or {}
    fields: dict[str, Any] = {
        "policy_id": policy_id,
        "dimension_weights": dict(dimension_weights or {}),
        "publication_threshold": float(publication_threshold),
    }
    fail = rules.get("gate_fail_threshold", rules.get("warn_min"))
    warn = rules.get("gate_warn_threshold", rules.get("pass_min"))
    if fail is not None:
        fields["warn_min"] = float(fail)
    if warn is not None:
        fields["pass_min"] = float(warn)
    if rules.get("critical_acceptance_threshold") is not None:
        fields["critical_acceptance_threshold"] = float(rules["critical_acceptance_threshold"])
    return ScoringPolicy(**fields)
