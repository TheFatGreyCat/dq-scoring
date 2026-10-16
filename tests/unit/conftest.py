"""Shared test fixtures and factory helpers for core unit tests."""

import pytest

from dq_scoring.core.models import (
    MeasurementStatus,
    QualityRuleResult,
    StandardDimension,
)


@pytest.fixture
def make_rule():
    """Factory fixture to create QualityRuleResult instances for tests."""

    def _factory(
        rule_id: str,
        status: str = MeasurementStatus.MEASURED.value,
        score: float | None = 85.0,
        is_required: bool = False,
        is_critical: bool = False,
        gate_enabled: bool = True,
        score_enabled: bool = True,
        is_primary: bool = True,
        violations: int = 0,
        dimension: str = StandardDimension.ACCURACY.value,
    ) -> QualityRuleResult:
        return QualityRuleResult(
            rule_id=rule_id,
            dimension=dimension,
            measurement_status=status,
            is_required=is_required,
            is_critical=is_critical,
            gate_enabled=gate_enabled,
            score_enabled=score_enabled,
            is_primary_scoring_rule=is_primary,
            computed_score=score,
            violations_count=violations,
        )

    return _factory
