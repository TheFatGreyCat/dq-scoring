"""Unit tests for Evaluation Worker Daemon and Standalone Spark Runner."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from dq_scoring.core.entities import ImmutableAssessment
from dq_scoring.core.models import PublicationStatus, QualityGateStatus
from dq_scoring.workers.daemon import run_daemon


def test_daemon_runs_and_stops_on_signal():
    """Verify daemon executes iterations and respects stop event cleanly."""
    with (
        patch("dq_scoring.workers.daemon.PostgresAssessmentStoreAdapter"),
        patch("dq_scoring.workers.daemon.PostgresQueueAdapter"),
        patch("dq_scoring.workers.daemon.PySparkComputeAdapter"),
        patch("dq_scoring.workers.daemon.EvaluationOrchestrator"),
        patch("dq_scoring.workers.daemon.EvaluationWorker") as mock_worker_cls,
    ):
        mock_worker = MagicMock()
        mock_worker._stop_event.is_set.side_effect = [False, False, True]
        dummy_assessment = ImmutableAssessment(
            assessment_id=uuid4(),
            tenant_id=uuid4(),
            run_id=uuid4(),
            snapshot_id=uuid4(),
            dq_score=95.5,
            publication_status=PublicationStatus.PUBLISHED,
            quality_gate=QualityGateStatus.PASS,
            coverage_ratio=1.0,
            dimension_results=[],
            assessment_hash="test-hash",
            created_at=datetime.now(UTC),
        )
        mock_worker.run_once.side_effect = [dummy_assessment, None]
        mock_worker_cls.return_value = mock_worker

        run_daemon()

        assert mock_worker.run_once.call_count == 2
        mock_worker_cls.assert_called_once()
