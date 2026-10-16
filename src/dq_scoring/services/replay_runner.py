"""Replay runner verifying deterministic reproducibility of assessments."""

from pydantic import BaseModel, ConfigDict

from dq_scoring.core.entities import ImmutableAssessment, LeasedRun
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator


class ReplayResult(BaseModel):
    """Result of replaying an evaluation run verifying determinism."""

    model_config = ConfigDict(frozen=True)

    is_replay_identical: bool
    expected_hash: str | None
    actual_hash: str
    assessment: ImmutableAssessment


class ReplayRunner:
    """Service executing replay runs and asserting byte-level deterministic parity."""

    def __init__(self, orchestrator: EvaluationOrchestrator) -> None:
        self._orchestrator = orchestrator

    def replay(
        self, leased_run: LeasedRun, expected_hash: str | None = None
    ) -> ReplayResult:
        """Execute run replay and verify assessment hash matches expected hash."""
        assessment = self._orchestrator.execute_leased_run(leased_run)
        actual_hash = assessment.assessment_hash
        is_identical = (
            actual_hash == expected_hash if expected_hash is not None else True
        )
        return ReplayResult(
            is_replay_identical=is_identical,
            expected_hash=expected_hash,
            actual_hash=actual_hash,
            assessment=assessment,
        )
