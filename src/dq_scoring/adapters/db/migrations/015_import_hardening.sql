-- ==============================================================================
-- Migration 015: Import Hardening - partial unique index for OBJECT_FILE,
-- relax legacy active-promotion unique index, and dispatcher session policies.
-- ==============================================================================

-- 1. Replace legacy dataset_snapshots UNIQUE(tenant_id, asset_id, content_sha256)
--    with partial unique index scoped to source_kind = 'OBJECT_FILE' so that
--    a CLI-migrated OBJECT_FILE successor of a legacy LOCAL_FILE snapshot sharing
--    identical raw bytes can be registered without constraint collision.
--    Preserve separate partial uniqueness for legacy LOCAL_FILE history.

ALTER TABLE dataset_snapshots
    DROP CONSTRAINT IF EXISTS dataset_snapshots_tenant_id_asset_id_content_sha256_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshots_object_file_sha
    ON dataset_snapshots(tenant_id, asset_id, content_sha256)
    WHERE source_kind = 'OBJECT_FILE';

CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshots_legacy_file_sha
    ON dataset_snapshots(tenant_id, asset_id, content_sha256)
    WHERE source_kind = 'LOCAL_FILE';

-- 2. Drop legacy single-active-promotion constraint on dataset_upload_sessions.
--    When multiple sessions for the same existing asset are uploaded/verified concurrently,
--    the old index `(tenant_id, asset_id) WHERE status IN ('VERIFYING', 'VERIFIED', 'PROMOTED')`
--    caused spurious UniqueViolation during worker claim UPDATE and permanently blocked
--    the SKIP LOCKED FIFO queue. Asset-level registration concurrency is already serialized
--    via SELECT ... FOR UPDATE on data_assets during register_snapshot().
DROP INDEX IF EXISTS uq_upload_active_promotion;

-- 3. Update dispatcher claim/lease policies to strictly allow worker claim and recovery.
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
