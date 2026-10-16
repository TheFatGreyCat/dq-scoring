CREATE TABLE worker_monitor_snapshots (
    worker_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('IMPORT', 'EVALUATION')),
    started_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    ready BOOLEAN NOT NULL,
    busy BOOLEAN NOT NULL,
    last_error_code TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'
);
GRANT SELECT ON worker_monitor_snapshots TO dq_app_role;
GRANT SELECT, INSERT, UPDATE ON worker_monitor_snapshots TO dq_worker_role;
