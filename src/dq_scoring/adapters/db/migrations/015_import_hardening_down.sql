-- ==============================================================================
-- Migration 015 Down: Revert partial unique indexes, restore full unique constraint
-- ==============================================================================

DO $$
BEGIN
    -- Refuse rollback if duplicates exist that would violate the combined constraint
    IF EXISTS (
        SELECT 1
        FROM dataset_snapshots
        GROUP BY tenant_id, asset_id, content_sha256
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Cannot roll back migration 015: duplicate (tenant_id, asset_id, content_sha256) snapshots exist across source kinds.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dataset_upload_sessions
        WHERE status IN ('VERIFYING', 'VERIFIED', 'PROMOTED')
          AND asset_id IS NOT NULL
        GROUP BY tenant_id, asset_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Cannot roll back migration 015: multiple active upload sessions exist for the same asset.';
    END IF;
END $$;

DROP INDEX IF EXISTS uq_snapshots_object_file_sha;
DROP INDEX IF EXISTS uq_snapshots_legacy_file_sha;

ALTER TABLE dataset_snapshots
    ADD CONSTRAINT dataset_snapshots_tenant_id_asset_id_content_sha256_key
    UNIQUE (tenant_id, asset_id, content_sha256);

CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_active_promotion
    ON dataset_upload_sessions(tenant_id, asset_id)
    WHERE status IN ('VERIFYING', 'VERIFIED', 'PROMOTED');
