-- Migration 019: Sensitive data findings counters, detectors metadata, and asset protection policy revisions

-- 1. Extend sensitive_data_findings with detector metadata and counts
ALTER TABLE sensitive_data_findings
    ADD COLUMN IF NOT EXISTS path TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS detector_code TEXT,
    ADD COLUMN IF NOT EXISTS detector_revision TEXT,
    ADD COLUMN IF NOT EXISTS matched_count BIGINT NOT NULL DEFAULT 0 CHECK (matched_count >= 0),
    ADD COLUMN IF NOT EXISTS observed_count BIGINT NOT NULL DEFAULT 0 CHECK (observed_count >= matched_count),
    ADD COLUMN IF NOT EXISTS detection_method TEXT CHECK (detection_method IS NULL OR detection_method IN ('VALUE_PATTERN', 'COLUMN_NAME', 'LEGACY'));

-- Unique index for deterministic upsert/registration of detector findings
CREATE UNIQUE INDEX IF NOT EXISTS uq_findings_detector
    ON sensitive_data_findings (tenant_id, snapshot_id, column_name, path, detector_code, detector_revision)
    WHERE detector_code IS NOT NULL;

-- 2. Expand data_protection_policies user_role constraint to include modern application roles
ALTER TABLE data_protection_policies DROP CONSTRAINT IF EXISTS data_protection_policies_user_role_check;
ALTER TABLE data_protection_policies ADD CONSTRAINT data_protection_policies_user_role_check
    CHECK (user_role IN (
        'WORKSPACE_ADMIN', 'DATA_OWNER', 'DATA_STEWARD', 'DATA_ENGINEER',
        'BUSINESS_VIEWER', 'VIEWER_UNPRIVILEGED', 'COMPLIANCE_AUDITOR'
    ));

-- 3. Versioned asset protection policy revisions
CREATE TABLE IF NOT EXISTS asset_protection_revisions (
    tenant_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    extra_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (tenant_id, asset_id),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE CASCADE
);

-- Enable and force row-level security for tenant isolation
ALTER TABLE asset_protection_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_protection_revisions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_asset_protection_revisions ON asset_protection_revisions;
CREATE POLICY tenant_isolation_asset_protection_revisions ON asset_protection_revisions
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

-- 4. Explicit permissions for application and worker service roles
GRANT SELECT, INSERT, UPDATE, DELETE ON asset_protection_revisions TO dq_app_role;
GRANT SELECT, INSERT, UPDATE ON sensitive_data_findings TO dq_app_role;
GRANT SELECT, INSERT, UPDATE ON sensitive_data_findings TO dq_worker_role;
GRANT SELECT ON asset_protection_revisions TO dq_worker_role;
