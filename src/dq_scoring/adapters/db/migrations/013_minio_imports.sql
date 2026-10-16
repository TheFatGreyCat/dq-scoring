-- ==============================================================================
-- Migration 013: MinIO object storage imports, JSONL format, and worker leases
-- ==============================================================================

-- 1. Extend format check constraints to support JSONL
ALTER TABLE data_assets DROP CONSTRAINT IF EXISTS data_assets_format_check;
ALTER TABLE data_assets ADD CONSTRAINT data_assets_format_check CHECK (format IN ('CSV', 'PARQUET', 'JSONL'));

ALTER TABLE dataset_upload_sessions DROP CONSTRAINT IF EXISTS dataset_upload_sessions_format_check;
ALTER TABLE dataset_upload_sessions ADD CONSTRAINT dataset_upload_sessions_format_check CHECK (format IN ('CSV', 'PARQUET', 'JSONL'));

-- 2. Default source_kind in snapshots to OBJECT_FILE
ALTER TABLE dataset_snapshots ALTER COLUMN source_kind SET DEFAULT 'OBJECT_FILE';

-- 3. Update dataset_upload_sessions schema
-- Allow asset_id to be nullable for un-registered sessions that specify asset_name
ALTER TABLE dataset_upload_sessions ALTER COLUMN asset_id DROP NOT NULL;

ALTER TABLE dataset_upload_sessions
    ADD COLUMN IF NOT EXISTS asset_name TEXT,
    ADD COLUMN IF NOT EXISTS client_request_id UUID,
    ADD COLUMN IF NOT EXISTS original_filename TEXT,
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS multipart_id TEXT,
    ADD COLUMN IF NOT EXISTS registered_snapshot_id UUID;

-- Session target constraint: unregistered requires XOR(asset_id, asset_name); registered allows both
ALTER TABLE dataset_upload_sessions
    ADD CONSTRAINT chk_upload_session_target
    CHECK (
        (status = 'REGISTERED' AND asset_id IS NOT NULL AND asset_name IS NOT NULL)
        OR (asset_id IS NOT NULL AND asset_name IS NULL)
        OR (asset_id IS NULL AND asset_name IS NOT NULL)
    );

-- Idempotency constraint per client request ID
CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_sessions_client_request
    ON dataset_upload_sessions(tenant_id, created_by, client_request_id)
    WHERE client_request_id IS NOT NULL;

-- FK to registered snapshot scoped by tenant
ALTER TABLE dataset_upload_sessions
    ADD CONSTRAINT fk_upload_registered_snapshot
    FOREIGN KEY (tenant_id, registered_snapshot_id)
    REFERENCES dataset_snapshots(tenant_id, snapshot_id)
    ON DELETE RESTRICT;

-- 4. Dispatcher policies for import workers claiming STAGED upload sessions
DROP POLICY IF EXISTS dispatcher_claim_upload_sessions ON dataset_upload_sessions;
DROP POLICY IF EXISTS dispatcher_lease_upload_sessions ON dataset_upload_sessions;

CREATE POLICY dispatcher_claim_upload_sessions ON dataset_upload_sessions
    FOR SELECT
    TO dq_dispatcher_role
    USING (status IN ('STAGED', 'VERIFYING'));

CREATE POLICY dispatcher_lease_upload_sessions ON dataset_upload_sessions
    FOR UPDATE
    TO dq_dispatcher_role
    USING (
        status = 'STAGED'
        OR (status = 'VERIFYING' AND lease_expires_at < now())
    )
    WITH CHECK (status IN ('VERIFYING', 'FAILED'));

GRANT SELECT, UPDATE ON dataset_upload_sessions TO dq_dispatcher_role;
