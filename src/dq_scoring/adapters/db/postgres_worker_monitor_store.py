"""Deployment metadata persistence, independent of job transactions."""

from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from dq_scoring.common.protected_transport import protected_connect


class PostgresWorkerMonitorStore:
    @staticmethod
    def write_snapshot(
        dsn: str,
        *,
        worker_id: str,
        kind: Literal["IMPORT", "EVALUATION"],
        started_at: datetime,
        ready: bool,
        busy: bool,
        last_error_code: str | None,
        metrics: dict[str, Any],
    ) -> None:
        with protected_connect(
            dsn, connect_timeout=2, options="-c statement_timeout=2000"
        ) as conn:
            conn.execute(
                """INSERT INTO worker_monitor_snapshots
                   (worker_id,kind,started_at,heartbeat_at,ready,busy,last_error_code,metrics)
                   VALUES (%s,%s,%s,now(),%s,%s,%s,%s)
                   ON CONFLICT (worker_id) DO UPDATE SET
                   kind=EXCLUDED.kind, started_at=EXCLUDED.started_at, heartbeat_at=now(),
                   ready=EXCLUDED.ready,busy=EXCLUDED.busy,
                   last_error_code=EXCLUDED.last_error_code,metrics=EXCLUDED.metrics""",
                (
                    worker_id,
                    kind,
                    started_at,
                    ready,
                    busy,
                    last_error_code,
                    Jsonb(metrics),
                ),
            )
