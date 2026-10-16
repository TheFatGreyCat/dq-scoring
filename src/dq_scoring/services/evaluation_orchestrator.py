"""Evaluation orchestrator coordinating end-to-end evaluation run lifecycle."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.core.dimension_scoring import required_dimensions
from dq_scoring.core.entities import (
    ImmutableAssessment,
    LeasedRun,
    RunStatus,
)
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.core.models import QualityRuleResult
from dq_scoring.core.outlier_advisory import (
    OutlierResultInput,
    build_outlier_advisory_result,
)
from dq_scoring.ports.assessment_store import IAssessmentStorePort
from dq_scoring.ports.compute_engine import IComputeEnginePort
from dq_scoring.ports.queue_port import IQueuePort
from dq_scoring.services.score_aggregator import ScoreAggregator, ScoreSummaryDTO
from dq_scoring.services.validation_service import ValidationService

logger = logging.getLogger(__name__)

GENERIC_RUN_FAILURE = "Evaluation failed due to an internal error. Contact an administrator with this run ID."


def safe_run_error(exc: Exception) -> str:
    """Message stored on the run and returned by the status API; never raw internals."""
    return str(exc) if isinstance(exc, RunAbortedError) else GENERIC_RUN_FAILURE


class EvaluationOrchestrator:
    """Orchestrates end-to-end execution of a leased data quality run."""

    def __init__(
        self,
        compute_engine: IComputeEnginePort,
        assessment_store: IAssessmentStorePort,
        queue_port: IQueuePort,
        validation_service: ValidationService | None = None,
        score_aggregator: ScoreAggregator | None = None,
    ) -> None:
        self._compute = compute_engine
        self._store = assessment_store
        self._queue = queue_port
        self._validation = validation_service or ValidationService(compute_engine)
        self._aggregator = score_aggregator or ScoreAggregator()

    def execute_leased_run(self, leased_run: LeasedRun) -> ImmutableAssessment:
        """Execute a leased evaluation run under monotonic lease protection."""
        if not self._queue.heartbeat(
            leased_run.run_id,
            leased_run.lease_generation,
            tenant_id=leased_run.spec.tenant_id,
        ):
            raise PermissionError(
                f"Lease fencing error: lease lost or expired for run {leased_run.run_id} (generation {leased_run.lease_generation})"
            )
        try:
            self._compute.verify_snapshot(leased_run.spec.snapshot)
            rule_results = self._execute_rules_and_advisories(leased_run)
            summary = self._aggregator.aggregate(
                rule_results=rule_results,
                policy=leased_run.spec.policy,
                required_dimensions=required_dimensions(rule_results),
                run_status=RunStatus.SUCCEEDED.value,
            )
            assessment = self._build_and_persist_assessment(
                leased_run, summary, rule_results
            )
            completed = self._queue.complete_run(
                run_id=leased_run.run_id,
                lease_generation=leased_run.lease_generation,
                status=RunStatus.SUCCEEDED,
                tenant_id=leased_run.spec.tenant_id,
            )
            if not completed:
                raise PermissionError(
                    f"Lease fencing error: failed to complete run {leased_run.run_id} (lease expired or superseded)"
                )
            return assessment
        except PermissionError:
            raise
        except Exception as exc:
            logger.exception("Run %s failed", leased_run.run_id)
            self._queue.complete_run(
                run_id=leased_run.run_id,
                lease_generation=leased_run.lease_generation,
                status=RunStatus.FAILED,
                error_message=safe_run_error(exc),
                tenant_id=leased_run.spec.tenant_id,
            )
            raise
        finally:
            self._compute.release_snapshot(leased_run.spec.snapshot)

    def _execute_rules_and_advisories(
        self, leased_run: LeasedRun
    ) -> list[QualityRuleResult]:
        """Execute standard rules and configured outlier advisory detections."""
        results = self._validation.validate_ruleset(
            snapshot=leased_run.spec.snapshot,
            rules=leased_run.spec.rules,
        )
        for col in leased_run.spec.outlier_columns:
            outlier_out = self._compute.detect_outliers(leased_run.spec.snapshot, col)
            results.append(
                build_outlier_advisory_result(
                    OutlierResultInput(
                        column_name=col,
                        total_evaluated=outlier_out.total_evaluated,
                        iqr=outlier_out.iqr,
                        outlier_count=outlier_out.outlier_count,
                    )
                )
            )
        return results

    def _build_and_persist_assessment(
        self,
        leased_run: LeasedRun,
        summary: ScoreSummaryDTO,
        rule_results: list[QualityRuleResult],
    ) -> ImmutableAssessment:
        """Construct immutable assessment, compute hash, and save atomically."""
        assessment_hash = self._compute_assessment_hash(
            leased_run, summary, rule_results
        )
        assessment = ImmutableAssessment(
            assessment_id=uuid4(),
            tenant_id=leased_run.spec.tenant_id,
            run_id=leased_run.run_id,
            snapshot_id=leased_run.spec.snapshot.snapshot_id,
            dq_score=summary.published_score,
            publication_status=summary.publication_status,
            coverage_ratio=summary.coverage_ratio,
            quality_gate=summary.quality_gate,
            dimension_results=summary.dimension_results,
            assessment_hash=assessment_hash,
            created_at=datetime.now(UTC),
        )
        self._compute.verify_snapshot(leased_run.spec.snapshot)
        self._store.save_assessment_atomic(
            assessment=assessment,
            rule_results=rule_results,
            lease_generation=leased_run.lease_generation,
        )
        return assessment

    def _compute_assessment_hash(
        self,
        leased_run: LeasedRun,
        summary: ScoreSummaryDTO,
        rule_results: list[QualityRuleResult],
    ) -> str:
        """Compute canonical deterministic SHA-256 hash for assessment."""
        payload: dict[str, Any] = {
            "snapshot_id": str(leased_run.spec.snapshot.snapshot_id),
            "dq_score": summary.published_score,
            "publication_status": summary.publication_status.value,
            "coverage_ratio": summary.coverage_ratio,
            "quality_gate": summary.quality_gate.value,
            "dimension_results": [
                {
                    "dimension": d.dimension,
                    "dimension_score": d.dimension_score,
                    "coverage_ratio": d.coverage_ratio,
                    "rules_count": len(d.rule_results),
                }
                for d in sorted(summary.dimension_results, key=lambda x: x.dimension)
            ],
            "rule_results": [
                {
                    "rule_id": r.rule_id,
                    "dimension": r.dimension,
                    "measurement_status": r.measurement_status,
                    "computed_score": r.computed_score,
                    "violations_count": r.violations_count,
                }
                for r in sorted(rule_results, key=lambda x: x.rule_id)
            ],
        }
        return compute_deterministic_hash(payload)
