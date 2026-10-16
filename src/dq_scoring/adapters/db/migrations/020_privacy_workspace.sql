-- Migration 020: Privacy workspace — column classifications, privacy change events,
-- versioned privacy detector rules, privacy scan jobs, and finding review metadata.
--
-- Legacy cutover: asset_protection_revisions.extra_columns is backfilled into
-- asset_column_classifications and then dropped; protection is resolved from classifications.
-- Legacy findings keep their detector uniqueness; new generations use scan-scoped rule identity.

-- 1. Column classifications declared per asset and canonical top-level column name
CREATE TABLE asset_column_classifications (
    tenant_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    column_name TEXT NOT NULL CHECK (char_length(column_name) > 0),
    category TEXT NOT NULL CHECK (category IN (
        'STANDARD_DATA', 'BASIC_PERSONAL_DATA', 'SENSITIVE_PERSONAL_DATA', 'CONFIDENTIAL_BUSINESS_DATA'
    )),
    updated_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 500 AND reason ~ '\S'),
    PRIMARY KEY (tenant_id, asset_id, column_name),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE CASCADE
);

-- 2. Append-only privacy change events (category/column/rule/finding identifiers only, never cell values or patterns)
CREATE TABLE privacy_change_events (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID,
    snapshot_id UUID,
    actor_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    before_state JSONB,
    after_state JSONB,
    reason TEXT CHECK (reason IS NULL OR (char_length(reason) BETWEEN 1 AND 500 AND reason ~ '\S')),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE RESTRICT
);
CREATE INDEX idx_privacy_change_events_asset ON privacy_change_events(tenant_id, asset_id, occurred_at DESC);

CREATE TRIGGER no_privacy_change_event_update BEFORE UPDATE OR DELETE ON privacy_change_events
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

-- 3. Privacy detector configuration version and append-only rule revisions
CREATE TABLE privacy_detector_configs (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0)
);

CREATE TABLE privacy_detector_rules (
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    rule_id UUID NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    code TEXT NOT NULL CHECK (code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    kind TEXT NOT NULL CHECK (kind IN ('BUILTIN', 'COLUMN_NAME', 'VALUE_PATTERN')),
    category TEXT NOT NULL CHECK (category IN (
        'BASIC_PERSONAL_DATA', 'SENSITIVE_PERSONAL_DATA', 'CONFIDENTIAL_BUSINESS_DATA'
    )),
    enabled BOOLEAN NOT NULL,
    builtin_code TEXT CHECK (builtin_code IS NULL OR builtin_code IN (
        'EMAIL', 'PHONE', 'CARD', 'SSN', 'VN_ID', 'PERSON_NAME', 'ADDRESS', 'BANK_ACCOUNT', 'SECRET'
    )),
    pattern TEXT CHECK (pattern IS NULL OR char_length(pattern) BETWEEN 1 AND 512),
    match_mode TEXT NOT NULL DEFAULT 'FULL' CHECK (match_mode IN ('FULL', 'SEARCH')),
    case_sensitive BOOLEAN NOT NULL DEFAULT TRUE,
    columns JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(columns) = 'array' AND jsonb_array_length(columns) <= 1000),
    created_by UUID REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, rule_id, revision),
    UNIQUE (tenant_id, code, revision),
    CHECK (
        (kind = 'BUILTIN' AND builtin_code IS NOT NULL AND pattern IS NULL)
        OR (kind <> 'BUILTIN' AND builtin_code IS NULL AND pattern IS NOT NULL)
    )
);
CREATE INDEX idx_privacy_detector_rules_latest ON privacy_detector_rules(tenant_id, rule_id, revision DESC);

-- Revisions are append-only: first revision is 1, each next is previous + 1, identity (code/kind/builtin_code)
-- is immutable, and a code cannot be reused by another rule_id. Service serializes writers on the config row.
CREATE FUNCTION enforce_privacy_rule_revision() RETURNS trigger AS $$
DECLARE
    prev privacy_detector_rules%ROWTYPE;
BEGIN
    IF EXISTS (
        SELECT 1 FROM privacy_detector_rules
        WHERE tenant_id = NEW.tenant_id AND code = NEW.code AND rule_id <> NEW.rule_id
    ) THEN
        RAISE EXCEPTION 'privacy rule code belongs to another rule' USING ERRCODE = 'unique_violation';
    END IF;

    SELECT * INTO prev FROM privacy_detector_rules
    WHERE tenant_id = NEW.tenant_id AND rule_id = NEW.rule_id
    ORDER BY revision DESC
    LIMIT 1;

    IF NOT FOUND THEN
        IF NEW.revision <> 1 THEN
            RAISE EXCEPTION 'first privacy rule revision must be 1' USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.revision <> prev.revision + 1
        OR NEW.code <> prev.code
        OR NEW.kind <> prev.kind
        OR NEW.builtin_code IS DISTINCT FROM prev.builtin_code THEN
        RAISE EXCEPTION 'privacy rule revisions are append-only with immutable identity' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_privacy_rule_revision BEFORE INSERT ON privacy_detector_rules
    FOR EACH ROW EXECUTE FUNCTION enforce_privacy_rule_revision();
CREATE TRIGGER no_privacy_rule_update BEFORE UPDATE OR DELETE ON privacy_detector_rules
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

-- 4. Privacy scan jobs (claim/lease/heartbeat mirrors dataset_upload_sessions from migration 013)
CREATE TABLE privacy_scan_jobs (
    scan_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    requested_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'QUEUED' CHECK (state IN ('QUEUED', 'RUNNING', 'COMPLETE', 'FAILED')),
    purpose TEXT NOT NULL CHECK (purpose IN ('APPLY', 'PREVIEW')),
    pinned_rules JSONB NOT NULL CHECK (jsonb_typeof(pinned_rules) = 'array'),
    config_version BIGINT NOT NULL CHECK (config_version >= 0),
    detector_digest TEXT NOT NULL CHECK (detector_digest ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_generation BIGINT NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error_code TEXT CHECK (error_code IS NULL OR (state = 'FAILED' AND error_code IN (
        'PRIVACY_RULE_INVALID', 'SNAPSHOT_REIMPORT_REQUIRED', 'OBJECT_CHANGED',
        'STORAGE_UNAVAILABLE', 'PRIVACY_SCAN_LIMIT_EXCEEDED', 'PRIVACY_SCAN_FAILED'
    ))),
    result_summary JSONB,
    UNIQUE (tenant_id, scan_id),
    UNIQUE (tenant_id, snapshot_id, scan_id),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_privacy_scan_jobs_active ON privacy_scan_jobs(tenant_id, snapshot_id, purpose)
    WHERE state IN ('QUEUED', 'RUNNING');
CREATE INDEX idx_privacy_scan_jobs_claim ON privacy_scan_jobs(state, lease_expires_at, created_at)
    WHERE state IN ('QUEUED', 'RUNNING');
CREATE INDEX idx_privacy_scan_jobs_latest ON privacy_scan_jobs(tenant_id, snapshot_id, purpose, created_at DESC, scan_id DESC);

-- Seed/backfill read tenant tables under FORCE RLS: error instead of silently skipping hidden rows.
SET LOCAL row_security = off;

-- 5. Seed the nine builtin detectors (revision 1) and config version 1 for existing tenants.
-- rule_id = uuid5(PRIVACY_RULE_NAMESPACE, '<tenant_id>:<builtin_code>'); the namespace literal is shared with
-- dq_scoring.services.privacy_service.PRIVACY_RULE_NAMESPACE, which lazy-initializes tenants created later.
INSERT INTO privacy_detector_configs (tenant_id, version)
SELECT tenant_id, 1 FROM tenants
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO privacy_detector_rules (tenant_id, rule_id, revision, code, kind, category, enabled, builtin_code)
SELECT t.tenant_id,
       uuid_generate_v5('6f1c2d8e-4b7a-5e93-a0d1-3c5e7f9b2a46'::UUID, t.tenant_id::TEXT || ':' || b.code),
       1, b.code, 'BUILTIN', b.category, TRUE, b.code
FROM tenants t
CROSS JOIN (VALUES
    ('EMAIL', 'BASIC_PERSONAL_DATA'),
    ('PHONE', 'BASIC_PERSONAL_DATA'),
    ('CARD', 'CONFIDENTIAL_BUSINESS_DATA'),
    ('SSN', 'SENSITIVE_PERSONAL_DATA'),
    ('VN_ID', 'SENSITIVE_PERSONAL_DATA'),
    ('PERSON_NAME', 'BASIC_PERSONAL_DATA'),
    ('ADDRESS', 'BASIC_PERSONAL_DATA'),
    ('BANK_ACCOUNT', 'CONFIDENTIAL_BUSINESS_DATA'),
    ('SECRET', 'CONFIDENTIAL_BUSINESS_DATA')
) AS b(code, category);

-- 6. Backfill explicit protected columns into manual classifications without overwriting any declaration
INSERT INTO asset_column_classifications (tenant_id, asset_id, column_name, category, updated_by, reason)
SELECT r.tenant_id, r.asset_id, col.name, 'CONFIDENTIAL_BUSINESS_DATA', a.created_by, 'Migrated explicit protected column'
FROM asset_protection_revisions r
JOIN data_assets a ON a.tenant_id = r.tenant_id AND a.asset_id = r.asset_id
CROSS JOIN LATERAL jsonb_array_elements_text(r.extra_columns) AS col(name)
WHERE char_length(col.name) > 0
ON CONFLICT (tenant_id, asset_id, column_name) DO NOTHING;

ALTER TABLE asset_protection_revisions DROP COLUMN extra_columns;

-- 7. Finding review metadata, privacy rule identity, and scan provenance
ALTER TABLE sensitive_data_findings
    ADD COLUMN review_reason TEXT CHECK (review_reason IS NULL OR (char_length(review_reason) BETWEEN 1 AND 500 AND review_reason ~ '\S')),
    ADD COLUMN reviewed_by UUID REFERENCES users(user_id) ON DELETE RESTRICT,
    ADD COLUMN reviewed_at TIMESTAMPTZ,
    ADD COLUMN privacy_rule_revision INTEGER CHECK (privacy_rule_revision IS NULL OR privacy_rule_revision >= 1),
    ADD COLUMN scan_id UUID;

ALTER TABLE sensitive_data_findings
    ADD CONSTRAINT chk_findings_privacy_rule_identity
        CHECK (privacy_rule_revision IS NULL OR detected_by_rule_id IS NOT NULL),
    ADD CONSTRAINT fk_findings_privacy_rule
        FOREIGN KEY (tenant_id, detected_by_rule_id, privacy_rule_revision)
        REFERENCES privacy_detector_rules(tenant_id, rule_id, revision) ON DELETE RESTRICT,
    ADD CONSTRAINT fk_findings_privacy_scan
        FOREIGN KEY (tenant_id, snapshot_id, scan_id)
        REFERENCES privacy_scan_jobs(tenant_id, snapshot_id, scan_id) ON DELETE RESTRICT;

ALTER TABLE sensitive_data_findings DROP CONSTRAINT IF EXISTS sensitive_data_findings_detection_method_check;
ALTER TABLE sensitive_data_findings ADD CONSTRAINT sensitive_data_findings_detection_method_check
    CHECK (detection_method IS NULL OR detection_method IN ('VALUE_PATTERN', 'COLUMN_NAME', 'CUSTOM_PATTERN', 'LEGACY'));

CREATE UNIQUE INDEX uq_findings_scan_rule
    ON sensitive_data_findings (tenant_id, scan_id, column_name, path, detected_by_rule_id, privacy_rule_revision)
    WHERE scan_id IS NOT NULL;

DROP INDEX uq_findings_detector;
CREATE UNIQUE INDEX uq_findings_detector ON sensitive_data_findings
    (tenant_id,snapshot_id,column_name,path,detector_code,detector_revision)
    WHERE detector_code IS NOT NULL AND scan_id IS NULL;

-- 8. Tenant isolation: ENABLE + FORCE RLS with USING and WITH CHECK
ALTER TABLE asset_column_classifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_column_classifications FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_asset_column_classifications ON asset_column_classifications
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE privacy_change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE privacy_change_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_privacy_change_events ON privacy_change_events
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE privacy_detector_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE privacy_detector_configs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_privacy_detector_configs ON privacy_detector_configs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE privacy_detector_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE privacy_detector_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_privacy_detector_rules ON privacy_detector_rules
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE privacy_scan_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE privacy_scan_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_privacy_scan_jobs ON privacy_scan_jobs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

-- Dispatcher claims QUEUED or lease-expired RUNNING scans across tenants, like migration 013 upload sessions
CREATE POLICY dispatcher_claim_privacy_scan_jobs ON privacy_scan_jobs
    FOR SELECT
    TO dq_dispatcher_role
    USING (state IN ('QUEUED', 'RUNNING'));

CREATE POLICY dispatcher_lease_privacy_scan_jobs ON privacy_scan_jobs
    FOR UPDATE
    TO dq_dispatcher_role
    USING (state = 'QUEUED' OR (state = 'RUNNING' AND lease_expires_at < now()))
    WITH CHECK (state IN ('RUNNING', 'FAILED'));

-- 9. Least-privilege grants (no BYPASSRLS, nothing to PUBLIC, no TRUNCATE)
GRANT SELECT, INSERT, UPDATE, DELETE ON asset_column_classifications TO dq_app_role;
GRANT SELECT, INSERT ON privacy_change_events TO dq_app_role;
GRANT SELECT, INSERT, UPDATE ON privacy_detector_configs TO dq_app_role;
GRANT SELECT, INSERT ON privacy_detector_rules TO dq_app_role;
GRANT SELECT, INSERT, UPDATE ON privacy_scan_jobs TO dq_app_role;

GRANT SELECT ON asset_column_classifications TO dq_worker_role;
GRANT INSERT ON privacy_change_events TO dq_worker_role;
GRANT UPDATE ON asset_protection_revisions TO dq_worker_role;
GRANT SELECT ON privacy_detector_configs, privacy_detector_rules TO dq_worker_role;
GRANT SELECT, UPDATE ON privacy_scan_jobs TO dq_worker_role;
GRANT SELECT, UPDATE ON privacy_scan_jobs TO dq_dispatcher_role;
