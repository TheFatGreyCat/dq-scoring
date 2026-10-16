-- ==============================================================================
-- Rollback Migration 013: MinIO object storage imports, JSONL format, and worker leases
-- ==============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM data_assets WHERE format = 'JSONL')
       OR EXISTS (SELECT 1 FROM dataset_upload_sessions WHERE format = 'JSONL')
       OR EXISTS (SELECT 1 FROM dataset_upload_sessions WHERE asset_id IS NULL OR client_request_id IS NOT NULL OR registered_snapshot_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Cannot roll back migration 013: JSONL records or new MinIO import sessions exist.';
    END IF;
END $$;

DROP POLICY IF EXISTS dispatcher_lease_upload_sessions ON dataset_upload_sessions;
DROP POLICY IF EXISTS dispatcher_claim_upload_sessions ON dataset_upload_sessions;
REVOKE SELECT, UPDATE ON dataset_upload_sessions FROM dq_dispatcher_role;

ALTER TABLE dataset_upload_sessions DROP CONSTRAINT IF EXISTS fk_upload_registered_snapshot;
DROP INDEX IF EXISTS uq_upload_sessions_client_request;
ALTER TABLE dataset_upload_sessions DROP CONSTRAINT IF EXISTS chk_upload_session_target;

ALTER TABLE dataset_upload_sessions
    DROP COLUMN IF EXISTS registered_snapshot_id,
    DROP COLUMN IF EXISTS multipart_id,
    DROP COLUMN IF EXISTS size_bytes,
    DROP COLUMN IF EXISTS original_filename,
    DROP COLUMN IF EXISTS client_request_id,
    DROP COLUMN IF EXISTS asset_name;

ALTER TABLE dataset_upload_sessions ALTER COLUMN asset_id SET NOT NULL;
ALTER TABLE dataset_snapshots ALTER COLUMN source_kind SET DEFAULT 'LOCAL_FILE';

ALTER TABLE dataset_upload_sessions DROP CONSTRAINT IF EXISTS dataset_upload_sessions_format_check;
ALTER TABLE dataset_upload_sessions ADD CONSTRAINT dataset_upload_sessions_format_check CHECK (format IN ('CSV', 'PARQUET'));

ALTER TABLE data_assets DROP CONSTRAINT IF EXISTS data_assets_format_check;
ALTER TABLE data_assets ADD CONSTRAINT data_assets_format_check CHECK (format IN ('CSV', 'PARQUET'));
