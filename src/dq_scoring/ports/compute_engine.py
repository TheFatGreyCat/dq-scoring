"""Abstract compute engine port for pushdown execution."""

from typing import Protocol, runtime_checkable

from dq_scoring.core.entities import (
    CanonicalMetric,
    DatasetSnapshot,
    OutlierExecutionOutput,
    QualityRule,
    RuleExecutionOutput,
)


@runtime_checkable
class IComputeEnginePort(Protocol):
    """Abstract port for compute plane operations (e.g. Apache Spark on k3s)."""

    def profile_snapshot(
        self, snapshot: DatasetSnapshot, columns: list[str]
    ) -> list[CanonicalMetric]:
        """Compute single-pass canonical profiling metrics for columns."""
        ...

    def execute_rules(
        self,
        snapshot: DatasetSnapshot,
        rules: list[QualityRule],
        sample_limit: int = 50,
    ) -> list[RuleExecutionOutput]:
        """Execute quality rules in a vectorized pushdown pass."""
        ...

    def detect_outliers(
        self,
        snapshot: DatasetSnapshot,
        column: str,
        k: float = 1.5,
        sample_limit: int = 50,
    ) -> OutlierExecutionOutput:
        """Detect numeric outliers using single-pass IQR calculation."""
        ...

    def verify_snapshot(self, snapshot: DatasetSnapshot) -> None:
        """Verify snapshot immutability, tenant boundary, and content checksum against storage."""
        ...

    def release_snapshot(self, snapshot: DatasetSnapshot) -> None:
        """Release run-scoped snapshot verification state."""
        ...
