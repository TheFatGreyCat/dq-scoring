from datetime import UTC, datetime
from threading import Event

import psycopg

from dq_scoring.workers.monitoring import WorkerMonitor, infrastructure_error_code


def test_monitor_continues_after_storage_failure_without_logging_secret(
    monkeypatch, caplog
):
    import dq_scoring.workers.monitoring as module

    finished = Event()
    snapshots = []

    def write(dsn, **snapshot):
        if not snapshots:
            snapshots.append(None)
            raise psycopg.OperationalError("synthetic password must not leak")
        snapshots.append(snapshot)
        finished.set()

    monkeypatch.setattr(module, "MONITOR_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(module.PostgresWorkerMonitorStore, "write_snapshot", write)
    monitor = WorkerMonitor("synthetic", "worker", "EVALUATION")
    monitor.queue_available()
    monitor.set_busy(True)
    monitor.start()
    assert finished.wait(2)
    monitor.stop()
    assert snapshots[1]["ready"] and snapshots[1]["busy"]
    assert snapshots[1]["started_at"] <= datetime.now(UTC)
    assert "MONITOR_WRITE_FAILED OperationalError" in caplog.text
    assert "synthetic password" not in caplog.text


def test_infrastructure_errors_are_codes_not_messages():
    assert (
        infrastructure_error_code(psycopg.OperationalError("secret"))
        == "DB_UNAVAILABLE"
    )
    assert infrastructure_error_code(RuntimeError("secret")) == "INFRASTRUCTURE_ERROR"
