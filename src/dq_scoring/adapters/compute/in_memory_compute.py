"""In-memory compute engine adapter for testing and offline runs."""

from uuid import UUID

from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.core.entities import (
    CanonicalMetric,
    DatasetSnapshot,
    OutlierExecutionOutput,
    QualityRule,
    RuleExecutionOutput,
)
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.core.models import MeasurementStatus, RuleCounts
from dq_scoring.ports.compute_engine import IComputeEnginePort


class InMemoryComputeAdapter(IComputeEnginePort):
    """In-memory compute adapter returning pre-configured or default execution outputs."""

    def __init__(self) -> None:
        self._preset_rule_outputs: dict[UUID, RuleExecutionOutput] = {}
        self._preset_outliers: dict[str, OutlierExecutionOutput] = {}
        self._preset_metrics: list[CanonicalMetric] = []
        self._registered_snapshots: dict[UUID, str] = {}

    def register_snapshot(self, snapshot: DatasetSnapshot) -> None:
        """Register snapshot identity hash for immutability verification."""
        self._registered_snapshots[snapshot.snapshot_id] = compute_deterministic_hash(
            snapshot.model_dump(mode="json")
        )

    def verify_snapshot(self, snapshot: DatasetSnapshot) -> None:
        """Verify snapshot identity against registered snapshot."""
        if snapshot.source_kind != "OBJECT_FILE":
            raise RunAbortedError("LEGACY_SOURCE_UNSUPPORTED: Local file snapshots are not supported.")
        registered = self._registered_snapshots.get(snapshot.snapshot_id)
        if registered is None:
            raise RunAbortedError("RESOURCE_NOT_FOUND: Snapshot identity is not registered.")
        if compute_deterministic_hash(snapshot.model_dump(mode="json")) != registered:
            raise RunAbortedError("OBJECT_CHANGED: Snapshot identity changed.")

    def release_snapshot(self, snapshot: DatasetSnapshot) -> None:
        self._registered_snapshots.pop(snapshot.snapshot_id, None)

    def set_rule_output(self, rule_id: UUID, output: RuleExecutionOutput) -> None:
        """Register a canned execution output for a specific rule."""
        self._preset_rule_outputs[rule_id] = output

    def set_outlier_output(self, column: str, output: OutlierExecutionOutput) -> None:
        """Register a canned outlier detection output for a specific column."""
        self._preset_outliers[column] = output

    def profile_snapshot(
        self, snapshot: DatasetSnapshot, columns: list[str]
    ) -> list[CanonicalMetric]:
        """Return preset or default profiling metrics."""
        if self._preset_metrics:
            return self._preset_metrics
        return [
            CanonicalMetric(
                metric_name="row_count",
                column_name=col,
                metric_value=snapshot.total_rows,
            )
            for col in columns
        ]

    def execute_rules(
        self,
        snapshot: DatasetSnapshot,
        rules: list[QualityRule],
        sample_limit: int = 50,
    ) -> list[RuleExecutionOutput]:
        """Return configured or perfect default outputs for each rule."""
        results: list[RuleExecutionOutput] = []
        for r in rules:
            if r.rule_id in self._preset_rule_outputs:
                results.append(self._preset_rule_outputs[r.rule_id])
            else:
                total = snapshot.total_rows
                results.append(
                    RuleExecutionOutput(
                        rule_id=r.rule_id,
                        counts=RuleCounts(
                            passed=total,
                            failed=0,
                            missing=0,
                            miscast=0,
                            not_applicable=0,
                            total_observed=total,
                        ),
                        status=MeasurementStatus.MEASURED,
                    )
                )
        return results

    def detect_outliers(
        self,
        snapshot: DatasetSnapshot,
        column: str,
        k: float = 1.5,
        sample_limit: int = 50,
    ) -> OutlierExecutionOutput:
        """Return preset or clean outlier execution output."""
        if column in self._preset_outliers:
            return self._preset_outliers[column]
        return OutlierExecutionOutput(
            column_name=column,
            total_evaluated=snapshot.total_rows,
            iqr=10.0,
            outlier_count=0,
        )
