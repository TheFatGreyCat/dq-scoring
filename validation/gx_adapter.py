from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dq_core.models import MeasurementResult, RecordMeasurementSummary


@dataclass(frozen=True)
class NormalizedExpectation:
    measurement: MeasurementResult
    summary: RecordMeasurementSummary


class MapExpectationAdapter:
    def normalize(self, validation_run_id: str, binding_id: str, raw: dict[str, Any]) -> NormalizedExpectation:
        result = raw.get("result", {})
        element_count = int(result.get("element_count") or 0)
        unexpected_count = int(result.get("unexpected_count") or 0)
        missing_count = int(result.get("missing_count") or 0)
        passed = max(element_count - unexpected_count - missing_count, 0)
        measurement_id = f"MR-{validation_run_id}-{binding_id}"
        measurement = MeasurementResult(
            measurement_result_id=measurement_id,
            validation_run_id=validation_run_id,
            binding_id=binding_id,
            evaluation_unit="record",
            expectation_success=raw.get("success"),
            measurement_status="measured",
            observed_value=result,
            expected_spec=raw.get("expectation_config", {}).get("kwargs", {}),
            failure_breakdown={"unexpected_count": unexpected_count, "missing_count": missing_count},
            backend="gx",
        )
        summary = RecordMeasurementSummary(measurement_id, passed, unexpected_count, missing_count, 0, passed + unexpected_count)
        return NormalizedExpectation(measurement, summary)


class AggregateExpectationAdapter:
    def normalize(self, validation_run_id: str, binding_id: str, raw: dict[str, Any]) -> NormalizedExpectation:
        result = raw.get("result", {})
        measurement_id = f"MR-{validation_run_id}-{binding_id}"
        success = raw.get("success")
        passed = 1 if success else 0
        failed = 0 if success else 1
        measurement = MeasurementResult(
            measurement_result_id=measurement_id,
            validation_run_id=validation_run_id,
            binding_id=binding_id,
            evaluation_unit="dataset_aggregate",
            expectation_success=success,
            measurement_status="measured",
            observed_value=result,
            expected_spec=raw.get("expectation_config", {}).get("kwargs", {}),
            failure_breakdown={} if success else {"aggregate_failed": True},
            backend="gx",
        )
        summary = RecordMeasurementSummary(measurement_id, passed, failed, 0, 0, 1)
        return NormalizedExpectation(measurement, summary)


class SpecialExpectationAdapter(AggregateExpectationAdapter):
    pass
