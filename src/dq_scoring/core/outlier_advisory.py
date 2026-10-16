"""Pure domain logic for IQR Outlier Advisory signal normalization (FR-DET-003..005)."""

from pydantic import BaseModel, ConfigDict

from dq_scoring.core.models import (
    MeasurementStatus,
    QualityRuleResult,
    StandardDimension,
)

MIN_OUTLIER_EVALUATION_SAMPLE: int = 4
"""Minimum distinct sample size required to calculate valid IQR boundaries."""


class OutlierResultInput(BaseModel):
    """Input payload representing raw statistical distribution summary."""

    model_config = ConfigDict(frozen=True)

    column_name: str
    total_evaluated: int
    iqr: float = 0.0
    outlier_count: int = 0
    is_all_null: bool = False


def build_outlier_advisory_result(inp: OutlierResultInput) -> QualityRuleResult:
    """Normalize IQR Outlier Detector outcome into an advisory Canonical Quality Result.

    Advisory isolation invariant:
      - is_advisory = True
      - contribution_weight = 0.0
      - score_enabled = False
      - gate_enabled = False
      - computed_score = None
    """
    is_valid_measurement = (
        not inp.is_all_null
        and inp.total_evaluated >= MIN_OUTLIER_EVALUATION_SAMPLE
        and inp.iqr > 0.0
    )
    status = (
        MeasurementStatus.MEASURED.value
        if is_valid_measurement
        else MeasurementStatus.NOT_MEASURABLE.value
    )

    return QualityRuleResult(
        rule_id=f"outlier_iqr_{inp.column_name}",
        dimension=StandardDimension.ACCURACY.value,
        measurement_status=status,
        is_critical=False,
        is_advisory=True,
        is_required=False,
        gate_enabled=False,
        score_enabled=False,
        conflict_group=None,
        is_primary_scoring_rule=False,
        contribution_weight=0.0,
        computed_score=None,
        violations_count=inp.outlier_count,
        source_kind="OUTLIER",
        target_column=inp.column_name,
    )
