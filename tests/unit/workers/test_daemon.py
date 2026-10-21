"""Unit tests for Evaluation Worker Daemon and Standalone Spark Runner."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from dq_scoring.core.entities import ImmutableAssessment
from dq_scoring.core.models import PublicationStatus, QualityGateStatus
from dq_scoring.workers.daemon import run_daemon


@pytest.mark.parametrize("lane", ["fast", "heavy"])
def test_daemon_runs_and_stops_on_signal(monkeypatch, lane):
    """Verify daemon executes iterations and respects stop event cleanly."""
    monkeypatch.setenv("DQ_WORKER_POSTGRES_DSN", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("DQ_WORKER_LANE", lane)
    with (
        patch("dq_scoring.workers.daemon.WorkerMonitor"),
        patch("dq_scoring.workers.daemon.RunSparkObserver"),
        patch("dq_scoring.workers.daemon.SnapshotProfileWorker") as profile_cls,
        patch("dq_scoring.workers.daemon.PostgresProfileQueue"),
        patch("dq_scoring.workers.daemon.validate_protected_runtime"),
        patch("dq_scoring.workers.daemon.require_protected_dsn", side_effect=lambda dsn: dsn),
        patch("dq_scoring.workers.daemon.FairProfileScheduler") as scheduler_cls,
        patch("dq_scoring.workers.daemon.time.sleep"),
        patch("dq_scoring.workers.daemon.signal.signal"),
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
        scheduler = scheduler_cls.return_value
        scheduler.run_once.side_effect = [dummy_assessment, None]
        mock_worker_cls.return_value = mock_worker

        run_daemon()

        assert scheduler.run_once.call_count == 2
        mock_worker_cls.assert_called_once()
        if lane == "fast":
            profile_cls.assert_called_once()
        else:
            profile_cls.assert_not_called()
