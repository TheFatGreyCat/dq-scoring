-- ==============================================================================
-- DQ Scoring Engine — Milestone 2 Initial Database Schema (PostgreSQL 16)
-- Conforms strictly to docs/Chapter_5.md §5.3.2, §5.3.3, §5.3.4
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- System Service Roles
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_dispatcher_role') THEN
        CREATE ROLE dq_dispatcher_role;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_janitor_role') THEN
        CREATE ROLE dq_janitor_role;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_app_role') THEN
        CREATE ROLE dq_app_role NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;

GRANT dq_dispatcher_role TO CURRENT_USER;
GRANT dq_janitor_role TO CURRENT_USER;
GRANT dq_app_role TO CURRENT_USER;

-- 0. Tenants
CREATE TABLE tenants (
    tenant_id UUID PRIMARY KEY,
    tenant_code TEXT NOT NULL UNIQUE,
    tenant_name TEXT NOT NULL,
    subscription_tier TEXT NOT NULL DEFAULT 'STANDARD' CHECK (subscription_tier IN ('STANDARD', 'ENTERPRISE')),
    max_concurrent_scheduled_runs INTEGER NOT NULL DEFAULT 2 CHECK (max_concurrent_scheduled_runs > 0),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, max_concurrent_scheduled_runs, status, created_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'default', 'Default Organization', 'ENTERPRISE', 4, 'ACTIVE', '2026-09-15T00:00:00Z')
ON CONFLICT (tenant_id) DO NOTHING;

-- 0b. Users
CREATE TABLE users (
    user_id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_email ON users(email);

INSERT INTO users (user_id, email, password_hash, full_name, is_active, email_verified, created_at)
VALUES ('00000000-0000-0000-0000-000000000002', 'admin@dqscoring.local', '$argon2id$v=19$m=65536,t=3,p=4$dummyhashforseedbaseline', 'Default System Admin', TRUE, TRUE, '2026-09-15T00:00:00Z')
ON CONFLICT (user_id) DO NOTHING;

-- 0c. Tenant Memberships
CREATE TABLE tenant_memberships (
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('WORKSPACE_ADMIN', 'DATA_OWNER', 'DATA_STEWARD', 'DATA_ENGINEER', 'BUSINESS_VIEWER')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);
CREATE INDEX idx_tenant_memberships_user ON tenant_memberships(user_id);

INSERT INTO tenant_memberships (tenant_id, user_id, role, status, joined_at)
VALUES ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002', 'WORKSPACE_ADMIN', 'ACTIVE', '2026-09-15T00:00:00Z')
ON CONFLICT (tenant_id, user_id) DO NOTHING;

-- 0d. User Sessions
CREATE TABLE user_sessions (
    session_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    refresh_token_hash TEXT NOT NULL UNIQUE,
    user_agent TEXT,
    client_ip TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_sessions_lookup ON user_sessions(user_id, tenant_id) WHERE revoked_at IS NULL;

-- 0e. User Invitations
CREATE TABLE user_invitations (
    invitation_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('WORKSPACE_ADMIN', 'DATA_OWNER', 'DATA_STEWARD', 'DATA_ENGINEER', 'BUSINESS_VIEWER')),
    token_hash TEXT NOT NULL UNIQUE,
    invited_by UUID NOT NULL REFERENCES users(user_id),
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_invitations_tenant ON user_invitations(tenant_id, email);


-- 1. Data Assets
CREATE TABLE data_assets (
    asset_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_name TEXT NOT NULL,
    slug TEXT NOT NULL,
    provenance_url TEXT,
    format TEXT NOT NULL CHECK (format IN ('CSV', 'PARQUET')),
    current_snapshot_id UUID,
    version_count INTEGER NOT NULL DEFAULT 0 CHECK (version_count >= 0),
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    owner_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    visibility_scope TEXT NOT NULL DEFAULT 'PRIVATE' CHECK (visibility_scope IN ('PRIVATE', 'WORKSPACE', 'MARKETPLACE_SHARED', 'PUBLIC_READ')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, asset_id)
);
CREATE UNIQUE INDEX uq_data_assets_tenant_name ON data_assets(tenant_id, asset_name);
CREATE UNIQUE INDEX uq_data_assets_tenant_slug ON data_assets(tenant_id, slug);
CREATE INDEX idx_data_assets_tenant_id ON data_assets(tenant_id);
CREATE INDEX idx_data_assets_owner ON data_assets(tenant_id, owner_user_id);
CREATE INDEX idx_data_assets_legal_hold ON data_assets(tenant_id, legal_hold) WHERE legal_hold = TRUE;

-- 1b. Access Grants
CREATE TABLE access_grants (
    grant_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('ASSET', 'SNAPSHOT', 'RULESET', 'POLICY', 'RUN', 'ASSESSMENT')),
    resource_id UUID NOT NULL,
    grantee_type TEXT NOT NULL CHECK (grantee_type IN ('USER', 'ROLE', 'TENANT', 'PUBLIC')),
    grantee_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('READ_METADATA', 'READ_SCORECARD', 'READ_EVIDENCE', 'EXECUTE_RUN', 'MANAGE')),
    granted_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by UUID REFERENCES users(user_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, grant_id)
);
CREATE INDEX idx_access_grants_lookup ON access_grants(tenant_id, resource_type, resource_id, grantee_type, grantee_id);
CREATE INDEX idx_access_grants_active ON access_grants(tenant_id, resource_id) WHERE revoked_at IS NULL;

-- 1c. Dataset Upload Sessions
CREATE TABLE dataset_upload_sessions (
    upload_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID NOT NULL,
    target_version_number INTEGER CHECK (target_version_number IS NULL OR target_version_number >= 1),
    claimed_sha256 TEXT CHECK (claimed_sha256 IS NULL OR length(claimed_sha256) = 64),
    computed_sha256 TEXT CHECK (computed_sha256 IS NULL OR length(computed_sha256) = 64),
    format TEXT NOT NULL CHECK (format IN ('CSV', 'PARQUET')),
    status TEXT NOT NULL CHECK (status IN ('INITIATED', 'UPLOADING', 'STAGED', 'VERIFYING', 'VERIFIED', 'PROMOTED', 'REGISTERED', 'CLEANED', 'REJECTED', 'ABORTED', 'FAILED')),
    staging_key TEXT NOT NULL,
    destination_location TEXT,
    manifest JSONB,
    error_reason TEXT,
    lease_owner TEXT,
    lease_generation BIGINT NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    fencing_token BIGINT NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, upload_id)
);
CREATE INDEX idx_upload_sessions_lookup ON dataset_upload_sessions(tenant_id, asset_id, status);
CREATE INDEX idx_upload_sessions_lease ON dataset_upload_sessions(status, lease_expires_at) WHERE status IN ('STAGED', 'VERIFYING', 'VERIFIED');
CREATE INDEX idx_upload_sessions_janitor ON dataset_upload_sessions(status, expires_at) WHERE status IN ('INITIATED', 'UPLOADING', 'REGISTERED', 'REJECTED', 'ABORTED', 'FAILED');
CREATE UNIQUE INDEX uq_upload_active_promotion ON dataset_upload_sessions(tenant_id, asset_id)
    WHERE status IN ('VERIFYING', 'VERIFIED', 'PROMOTED');

-- 2. Dataset Snapshots
CREATE TABLE dataset_snapshots (
    snapshot_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    version_tag TEXT,
    version_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (version_status IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED')),
    parent_snapshot_id UUID,
    source_kind TEXT NOT NULL DEFAULT 'LOCAL_FILE' CHECK (source_kind IN ('LOCAL_FILE', 'OBJECT_FILE', 'DELTA_TABLE')),
    source_descriptor JSONB NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    manifest JSONB,
    storage_location TEXT NOT NULL,
    schema_definition JSONB NOT NULL,
    total_rows BIGINT NOT NULL CHECK (total_rows >= 0),
    total_columns INTEGER NOT NULL CHECK (total_columns > 0),
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    captured_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, parent_snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE SET NULL (parent_snapshot_id),
    UNIQUE (tenant_id, snapshot_id),
    UNIQUE (tenant_id, asset_id, snapshot_id),
    UNIQUE (tenant_id, asset_id, version_number),
    UNIQUE (tenant_id, asset_id, content_sha256)
);
CREATE INDEX idx_snapshots_tenant_asset_version ON dataset_snapshots(tenant_id, asset_id, version_number DESC);
CREATE INDEX idx_snapshots_tenant_asset_status ON dataset_snapshots(tenant_id, asset_id, version_status);
CREATE INDEX idx_snapshots_source_kind ON dataset_snapshots(source_kind);

ALTER TABLE data_assets ADD CONSTRAINT fk_data_assets_current_snapshot
    FOREIGN KEY (tenant_id, asset_id, current_snapshot_id) REFERENCES dataset_snapshots(tenant_id, asset_id, snapshot_id) DEFERRABLE INITIALLY DEFERRED;

-- 3. Canonical Metrics
CREATE TABLE canonical_metrics (
    metric_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    column_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    summary_payload JSONB,
    method TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE CASCADE
);
CREATE INDEX idx_metrics_tenant_snapshot_col ON canonical_metrics(tenant_id, snapshot_id, column_name);

-- 3b. Sensitive Data Findings
CREATE TABLE sensitive_data_findings (
    finding_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    run_id UUID,
    column_name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('BASIC_PERSONAL_DATA', 'SENSITIVE_PERSONAL_DATA', 'CONFIDENTIAL_BUSINESS_DATA', 'STANDARD_DATA')),
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0.0 AND 1.0),
    detected_by_rule_id UUID,
    status TEXT NOT NULL DEFAULT 'DETECTED' CHECK (status IN ('DETECTED', 'CONFIRMED', 'DISMISSED')),
    detected_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE CASCADE
);
CREATE INDEX idx_findings_tenant_snapshot ON sensitive_data_findings(tenant_id, snapshot_id);
CREATE INDEX idx_findings_category ON sensitive_data_findings(category);


-- 4. Ruleset Templates
CREATE TABLE ruleset_templates (
    template_id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    template_code TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL CHECK (domain IN ('FINANCE', 'RETAIL', 'HEALTHCARE', 'TRANSPORTATION', 'GENERAL')),
    data_type TEXT NOT NULL CHECK (data_type IN ('TRANSACTION_EVENT', 'MASTER_DATA', 'DIMENSION_TABLE', 'TIMESERIES')),
    target_use_case TEXT NOT NULL,
    description TEXT,
    rules_payload JSONB NOT NULL,
    is_system_template BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_ruleset_template_code_scope ON ruleset_templates(
    COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::UUID),
    template_code
);
CREATE INDEX idx_ruleset_templates_domain ON ruleset_templates(domain, data_type);

-- 4b. Rulesets
CREATE TABLE rulesets (
    ruleset_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID,
    derived_from_template_id UUID REFERENCES ruleset_templates(template_id) ON DELETE SET NULL,
    version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')),
    created_by UUID NOT NULL REFERENCES users(user_id),
    submitted_by UUID NOT NULL REFERENCES users(user_id),
    submitted_at TIMESTAMPTZ NOT NULL,
    approved_by UUID REFERENCES users(user_id),
    approved_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE RESTRICT,
    CHECK (status <> 'ACTIVE' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
    UNIQUE (tenant_id, ruleset_id),
    UNIQUE (tenant_id, version)
);
CREATE INDEX idx_rulesets_tenant_asset ON rulesets(tenant_id, asset_id);
CREATE INDEX idx_rulesets_tenant_hash ON rulesets(tenant_id, config_hash);
CREATE INDEX idx_rulesets_derived_template ON rulesets(derived_from_template_id);
CREATE UNIQUE INDEX uq_rulesets_tenant_asset_active ON rulesets(tenant_id, asset_id, status)
    WHERE status = 'ACTIVE' AND asset_id IS NOT NULL;

-- 4c. Rule Catalog Templates
CREATE TABLE rule_catalog_templates (
    template_id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    template_code TEXT NOT NULL,
    name TEXT NOT NULL,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('NON_NULL', 'TYPE_PARSE', 'DOMAIN_RANGE', 'UNIQUENESS', 'CROSS_FIELD')),
    parameter_schema JSONB NOT NULL,
    default_null_policy TEXT NOT NULL CHECK (default_null_policy IN ('FAIL', 'IGNORE', 'SEPARATE', 'NOT_APPLICABLE')),
    default_dimension TEXT NOT NULL CHECK (default_dimension IN ('COMPLETENESS', 'ACCURACY', 'CONSISTENCY', 'TIMELINESS', 'UNIQUENESS', 'VALIDITY')),
    is_advisory_default BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX uq_template_code_scope ON rule_catalog_templates(
    COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::UUID),
    template_code
);

-- 4d. Classification Rules
CREATE TABLE classification_rules (
    rule_id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    rule_name TEXT NOT NULL,
    target_category TEXT NOT NULL CHECK (target_category IN ('BASIC_PERSONAL_DATA', 'SENSITIVE_PERSONAL_DATA', 'CONFIDENTIAL_BUSINESS_DATA')),
    pattern_type TEXT NOT NULL CHECK (pattern_type IN ('COLUMN_NAME_REGEX', 'VALUE_FORMAT_REGEX', 'SEMANTIC_PROFILE')),
    pattern_regex TEXT NOT NULL,
    confidence_threshold REAL NOT NULL DEFAULT 0.80 CHECK (confidence_threshold BETWEEN 0.0 AND 1.0),
    priority INTEGER NOT NULL DEFAULT 100
);
CREATE INDEX idx_classification_tenant ON classification_rules(tenant_id);

-- 4e. Data Protection Policies
CREATE TABLE data_protection_policies (
    policy_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID,
    target_category TEXT NOT NULL CHECK (target_category IN ('BASIC_PERSONAL_DATA', 'SENSITIVE_PERSONAL_DATA', 'CONFIDENTIAL_BUSINESS_DATA', 'STANDARD_DATA')),
    user_role TEXT NOT NULL CHECK (user_role IN ('DATA_OWNER', 'DATA_STEWARD', 'COMPLIANCE_AUDITOR', 'VIEWER_UNPRIVILEGED')),
    masking_strategy TEXT NOT NULL CHECK (masking_strategy IN ('FULL_MASK', 'PARTIAL_MASK', 'HASH_SHA256', 'TOKENIZE', 'PLAINTEXT')),
    masking_parameters JSONB NOT NULL DEFAULT '{}'::JSONB,
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_protection_policies ON data_protection_policies(
    tenant_id,
    COALESCE(asset_id, '00000000-0000-0000-0000-000000000000'::UUID),
    target_category,
    user_role
);


-- 5. Quality Rules
CREATE TABLE quality_rules (
    rule_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    ruleset_id UUID NOT NULL,
    template_id UUID REFERENCES rule_catalog_templates(template_id) ON DELETE SET NULL,
    rule_name TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('COMPLETENESS', 'ACCURACY', 'CONSISTENCY', 'TIMELINESS', 'UNIQUENESS', 'VALIDITY')),
    target_column TEXT NOT NULL,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('NON_NULL', 'TYPE_PARSE', 'DOMAIN_RANGE', 'UNIQUENESS', 'CROSS_FIELD')),
    parameters JSONB NOT NULL,
    null_policy TEXT NOT NULL CHECK (null_policy IN ('FAIL', 'IGNORE', 'SEPARATE', 'NOT_APPLICABLE')),
    weight REAL NOT NULL DEFAULT 1.0 CHECK (weight > 0),
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'STANDARD')),
    is_advisory BOOLEAN NOT NULL DEFAULT FALSE,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    gate_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    score_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    acceptance_threshold REAL CHECK (acceptance_threshold IS NULL OR (acceptance_threshold BETWEEN 0 AND 100)),
    conflict_group TEXT,
    is_primary_scoring_rule BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL DEFAULT 'USER' CHECK (source IN ('USER', 'CATALOG', 'AI_ADVISORY')),
    FOREIGN KEY (tenant_id, ruleset_id) REFERENCES rulesets(tenant_id, ruleset_id) ON DELETE CASCADE,
    CHECK (NOT (is_required = TRUE AND (is_advisory = TRUE OR source = 'AI_ADVISORY'))),
    CHECK (NOT (is_advisory = TRUE AND score_enabled = TRUE)),
    UNIQUE (tenant_id, rule_id)
);
CREATE INDEX idx_rules_tenant_ruleset ON quality_rules(tenant_id, ruleset_id);
CREATE INDEX idx_rules_template_id ON quality_rules(template_id);
CREATE INDEX idx_rules_source ON quality_rules(source);
CREATE UNIQUE INDEX uq_rules_primary_in_conflict_group 
    ON quality_rules(tenant_id, ruleset_id, conflict_group) 
    WHERE conflict_group IS NOT NULL AND is_primary_scoring_rule = TRUE;

-- 6. Scoring Policy Templates
CREATE TABLE scoring_policy_templates (
    template_id UUID PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    template_code TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL CHECK (domain IN ('FINANCE', 'RETAIL', 'HEALTHCARE', 'TRANSPORTATION', 'GENERAL')),
    target_use_case TEXT NOT NULL,
    description TEXT,
    dimension_weights JSONB NOT NULL,
    publication_threshold REAL NOT NULL DEFAULT 0.80 CHECK (publication_threshold BETWEEN 0 AND 1),
    gate_rules JSONB NOT NULL,
    is_system_template BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_policy_template_code_scope ON scoring_policy_templates(
    COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::UUID),
    template_code
);
CREATE INDEX idx_policy_templates_domain ON scoring_policy_templates(domain);


-- 6b. Scoring Policies
CREATE TABLE scoring_policies (
    policy_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    derived_from_template_id UUID REFERENCES scoring_policy_templates(template_id) ON DELETE SET NULL,
    version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')),
    created_by UUID NOT NULL REFERENCES users(user_id),
    submitted_by UUID NOT NULL REFERENCES users(user_id),
    submitted_at TIMESTAMPTZ NOT NULL,
    approved_by UUID REFERENCES users(user_id),
    approved_at TIMESTAMPTZ,
    dimension_weights JSONB NOT NULL,
    publication_threshold REAL NOT NULL DEFAULT 0.80 CHECK (publication_threshold BETWEEN 0 AND 1),
    gate_rules JSONB NOT NULL,
    CHECK (status <> 'ACTIVE' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
    UNIQUE (tenant_id, policy_id),
    UNIQUE (tenant_id, version)
);
CREATE INDEX idx_scoring_policies_tenant_hash ON scoring_policies(tenant_id, config_hash);
CREATE INDEX idx_scoring_policies_derived_template ON scoring_policies(derived_from_template_id);
CREATE UNIQUE INDEX uq_policies_tenant_active ON scoring_policies(tenant_id, status) WHERE status = 'ACTIVE';

-- 6c. Evaluation Schedules
CREATE TABLE evaluation_schedules (
    schedule_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID NOT NULL,
    ruleset_id UUID NOT NULL,
    policy_id UUID NOT NULL,
    schedule_name TEXT NOT NULL,
    cadence TEXT NOT NULL CHECK (cadence IN ('MONTHLY', 'QUARTERLY', 'YEARLY', 'CRON')),
    cron_expression TEXT,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    snapshot_selection_policy TEXT NOT NULL DEFAULT 'LATEST_ACTIVE' CHECK (snapshot_selection_policy IN ('LATEST_ACTIVE', 'PINNED_VERSION')),
    pinned_snapshot_id UUID,
    execution_profile TEXT NOT NULL DEFAULT 'SPARK_K3S' CHECK (execution_profile IN ('SPARK_K3S')),
    workload_tier TEXT NOT NULL DEFAULT 'SMALL' CHECK (workload_tier IN ('SMALL', 'LARGE')),
    priority INTEGER NOT NULL DEFAULT 10 CHECK (priority BETWEEN 1 AND 10),
    catchup_policy TEXT NOT NULL DEFAULT 'SKIP_MISSED' CHECK (catchup_policy IN ('SKIP_MISSED', 'RUN_LATEST_ONLY')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PAUSED', 'DISABLED')),
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ NOT NULL,
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES data_assets(tenant_id, asset_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, ruleset_id) REFERENCES rulesets(tenant_id, ruleset_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, policy_id) REFERENCES scoring_policies(tenant_id, policy_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, asset_id, pinned_snapshot_id) REFERENCES dataset_snapshots(tenant_id, asset_id, snapshot_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, schedule_id)
);
CREATE INDEX idx_schedules_due ON evaluation_schedules(next_run_at ASC) WHERE status = 'ACTIVE';
CREATE INDEX idx_schedules_tenant_asset ON evaluation_schedules(tenant_id, asset_id);


-- 7. Evaluation Runs
CREATE TABLE evaluation_runs (
    run_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    ruleset_id UUID NOT NULL,
    policy_id UUID NOT NULL,
    schedule_id UUID,
    workload_tier TEXT NOT NULL DEFAULT 'SMALL' CHECK (workload_tier IN ('SMALL', 'LARGE')),
    trigger_type TEXT NOT NULL DEFAULT 'ON_DEMAND' CHECK (trigger_type IN ('ON_DEMAND', 'SCHEDULED', 'RE_SCAN', 'API')),
    version_number INTEGER,
    execution_profile TEXT NOT NULL DEFAULT 'SPARK_K3S' CHECK (execution_profile IN ('SPARK_K3S')),
    submission_token TEXT,
    platform_app_id TEXT,
    driver_status TEXT,
    outlier_config JSONB NOT NULL,
    outlier_config_hash TEXT NOT NULL,
    classification_rules_revision TEXT,
    priority INTEGER NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    run_status TEXT NOT NULL CHECK (run_status IN ('QUEUED', 'LEASED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner TEXT,
    lease_generation BIGINT NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_key TEXT NOT NULL,
    execution_error TEXT,
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, ruleset_id) REFERENCES rulesets(tenant_id, ruleset_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, policy_id) REFERENCES scoring_policies(tenant_id, policy_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, schedule_id) REFERENCES evaluation_schedules(tenant_id, schedule_id) ON DELETE SET NULL (schedule_id),
    UNIQUE (tenant_id, run_id),
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX idx_runs_queued_fast ON evaluation_runs(priority ASC, created_at ASC)
    WHERE run_status = 'QUEUED' AND trigger_type != 'SCHEDULED' AND workload_tier = 'SMALL';
CREATE INDEX idx_runs_queued_heavy ON evaluation_runs(priority ASC, created_at ASC)
    WHERE run_status = 'QUEUED' AND trigger_type != 'SCHEDULED' AND workload_tier = 'LARGE';
CREATE INDEX idx_runs_queued_scheduled ON evaluation_runs(priority ASC, created_at ASC)
    WHERE run_status = 'QUEUED' AND trigger_type = 'SCHEDULED';
CREATE INDEX idx_runs_tenant_snapshot ON evaluation_runs(tenant_id, snapshot_id);
CREATE INDEX idx_runs_status ON evaluation_runs(run_status);
CREATE INDEX idx_runs_lease_expiry ON evaluation_runs(lease_expires_at)
    WHERE run_status IN ('LEASED', 'RUNNING');

CREATE OR REPLACE FUNCTION notify_run_queued() RETURNS trigger AS $$
BEGIN
    IF NEW.run_status = 'QUEUED' AND (TG_OP = 'INSERT' OR OLD.run_status IS DISTINCT FROM 'QUEUED') THEN
        PERFORM pg_notify('dq_run_queued', NEW.run_id::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_notify_run_queued
    AFTER INSERT OR UPDATE OF run_status ON evaluation_runs
    FOR EACH ROW EXECUTE FUNCTION notify_run_queued();


-- 7a. Run Events
CREATE TABLE run_events (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    run_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
    lease_generation BIGINT,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, run_id) REFERENCES evaluation_runs(tenant_id, run_id) ON DELETE CASCADE
);
CREATE INDEX idx_run_events_tenant_run_created ON run_events(tenant_id, run_id, created_at);

-- 8. Canonical Quality Results
CREATE TABLE canonical_quality_results (
    result_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    run_id UUID NOT NULL,
    rule_id UUID,
    ruleset_id UUID,
    rule_config_hash TEXT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('RULE', 'OUTLIER', 'DRIFT')),
    target_column TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('COMPLETENESS', 'ACCURACY', 'CONSISTENCY', 'TIMELINESS', 'UNIQUENESS', 'VALIDITY')),
    measurement_status TEXT NOT NULL CHECK (measurement_status IN ('MEASURED', 'NOT_APPLICABLE', 'NOT_MEASURABLE', 'INSUFFICIENT_DATA', 'SKIPPED_BY_BUDGET', 'FAILED_TO_MEASURE')),
    passed_count BIGINT NOT NULL DEFAULT 0 CHECK (passed_count >= 0),
    failed_count BIGINT NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    missing_count BIGINT NOT NULL DEFAULT 0 CHECK (missing_count >= 0),
    miscast_count BIGINT NOT NULL DEFAULT 0 CHECK (miscast_count >= 0),
    not_applicable_count BIGINT NOT NULL DEFAULT 0 CHECK (not_applicable_count >= 0),
    total_observed BIGINT NOT NULL CHECK (total_observed >= 0),
    computed_score REAL CHECK (computed_score IS NULL OR (computed_score BETWEEN 0 AND 100)),
    is_advisory BOOLEAN NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    gate_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    score_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    evidence_payload JSONB,
    FOREIGN KEY (tenant_id, run_id) REFERENCES evaluation_runs(tenant_id, run_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, rule_id) REFERENCES quality_rules(tenant_id, rule_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, ruleset_id) REFERENCES rulesets(tenant_id, ruleset_id) ON DELETE RESTRICT,
    CHECK (octet_length(COALESCE(evidence_payload::text, '')) <= 512000),
    CHECK (passed_count + failed_count + missing_count + miscast_count + not_applicable_count = total_observed)
);
CREATE INDEX idx_results_tenant_run ON canonical_quality_results(tenant_id, run_id);
CREATE INDEX idx_results_status ON canonical_quality_results(measurement_status);
CREATE INDEX idx_results_rule_id ON canonical_quality_results(rule_id);


-- 9. Assessments
CREATE TABLE assessments (
    assessment_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    run_id UUID NOT NULL UNIQUE,
    snapshot_id UUID NOT NULL,
    dq_score REAL CHECK (dq_score IS NULL OR (dq_score BETWEEN 0 AND 100)),
    publication_status TEXT NOT NULL CHECK (publication_status IN ('PUBLISHED', 'WITHHELD')),
    visibility_scope TEXT NOT NULL DEFAULT 'PRIVATE' CHECK (visibility_scope IN ('PRIVATE', 'WORKSPACE', 'MARKETPLACE_SHARED', 'PUBLIC_READ')),
    coverage_ratio REAL CHECK (coverage_ratio IS NULL OR (coverage_ratio BETWEEN 0 AND 1)),
    confidence_status TEXT NOT NULL,
    quality_gate TEXT NOT NULL CHECK (quality_gate IN ('PASS', 'WARN', 'FAIL', 'INSUFFICIENT_EVIDENCE', 'ERROR')),
    config_hashes JSONB NOT NULL,
    assessment_hash TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (tenant_id, run_id) REFERENCES evaluation_runs(tenant_id, run_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE RESTRICT,
    UNIQUE (tenant_id, assessment_id),
    CHECK (
        (publication_status = 'PUBLISHED' AND dq_score IS NOT NULL)
        OR (publication_status = 'WITHHELD' AND dq_score IS NULL)
    )
);
CREATE INDEX idx_assessments_tenant_snapshot ON assessments(tenant_id, snapshot_id);
CREATE INDEX idx_assessments_gate ON assessments(quality_gate);
CREATE INDEX idx_assessments_hash ON assessments(assessment_hash);

-- 10. Dimension Results
CREATE TABLE dimension_results (
    dimension_result_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    assessment_id UUID NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('COMPLETENESS', 'ACCURACY', 'CONSISTENCY', 'TIMELINESS', 'UNIQUENESS', 'VALIDITY')),
    measurement_status TEXT NOT NULL CHECK (measurement_status IN ('MEASURED', 'NOT_APPLICABLE', 'NOT_MEASURABLE', 'INSUFFICIENT_DATA', 'SKIPPED_BY_BUDGET', 'FAILED_TO_MEASURE')),
    dimension_score REAL CHECK (dimension_score IS NULL OR (dimension_score BETWEEN 0 AND 100)),
    dimension_weight REAL NOT NULL CHECK (dimension_weight >= 0),
    total_rules INTEGER NOT NULL CHECK (total_rules >= 0),
    measured_rules INTEGER NOT NULL CHECK (measured_rules >= 0),
    FOREIGN KEY (tenant_id, assessment_id) REFERENCES assessments(tenant_id, assessment_id) ON DELETE CASCADE,
    UNIQUE (tenant_id, assessment_id, dimension),
    CHECK (measured_rules <= total_rules),
    CHECK (
        (measurement_status = 'MEASURED' AND dimension_score IS NOT NULL)
        OR (measurement_status <> 'MEASURED' AND dimension_score IS NULL)
    )
);
CREATE INDEX idx_dim_results_tenant_assessment ON dimension_results(tenant_id, assessment_id);

-- 11. Assessment Outbox
CREATE TABLE assessment_outbox (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    assessment_id UUID NOT NULL,
    destination TEXT NOT NULL DEFAULT 'LAKEHOUSE_DELTA',
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSED', 'FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, assessment_id) REFERENCES assessments(tenant_id, assessment_id) ON DELETE CASCADE
);
CREATE INDEX idx_outbox_tenant_status_created ON assessment_outbox(tenant_id, status, created_at);


-- 12. Notification Channels
CREATE TABLE notification_channels (
    channel_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    channel_type TEXT NOT NULL CHECK (channel_type IN ('EMAIL', 'WEBHOOK', 'SLACK', 'TEAMS')),
    name TEXT NOT NULL,
    config_json JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, channel_id),
    UNIQUE (tenant_id, name)
);
CREATE INDEX idx_notif_channels_tenant ON notification_channels(tenant_id, is_active);

-- 13. Alert Subscriptions
CREATE TABLE alert_subscriptions (
    subscription_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    channel_id UUID NOT NULL,
    event_types TEXT[] NOT NULL,
    min_severity TEXT NOT NULL DEFAULT 'WARN' CHECK (min_severity IN ('INFO', 'WARN', 'CRITICAL')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES notification_channels(tenant_id, channel_id) ON DELETE CASCADE,
    UNIQUE (tenant_id, subscription_id)
);
CREATE INDEX idx_alert_subscriptions_lookup ON alert_subscriptions(tenant_id, user_id, is_active);

-- 14. Notification Logs
CREATE TABLE notification_logs (
    log_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    channel_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    recipient TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (delivery_status IN ('PENDING', 'DELIVERED', 'FAILED', 'SSRF_BLOCKED')),
    retry_count INT NOT NULL DEFAULT 0,
    error_message TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, channel_id) REFERENCES notification_channels(tenant_id, channel_id) ON DELETE CASCADE
);
CREATE INDEX idx_notif_logs_status ON notification_logs(tenant_id, delivery_status, created_at);

-- 15. Audit Logs
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    actor_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    client_ip TEXT,
    user_agent TEXT,
    diff_json JSONB,
    prev_log_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, audit_id)
);
CREATE INDEX idx_audit_logs_tenant_resource ON audit_logs(tenant_id, resource_type, resource_id);
CREATE INDEX idx_audit_logs_actor ON audit_logs(tenant_id, actor_user_id, event_timestamp);

-- 16. Retention Audit Logs
CREATE TABLE retention_audit_logs (
    retention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    subscription_tier TEXT NOT NULL,
    retention_cutoff_used TIMESTAMPTZ NOT NULL,
    runs_evaluated INTEGER NOT NULL CHECK (runs_evaluated >= 0),
    runs_deleted INTEGER NOT NULL CHECK (runs_deleted >= 0),
    assessments_deleted INTEGER NOT NULL CHECK (assessments_deleted >= 0),
    quality_results_deleted INTEGER NOT NULL CHECK (quality_results_deleted >= 0),
    run_events_deleted INTEGER NOT NULL CHECK (run_events_deleted >= 0),
    is_dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    executed_by TEXT NOT NULL DEFAULT session_user,
    execution_duration_ms INTEGER NOT NULL CHECK (execution_duration_ms >= 0),
    execution_status TEXT NOT NULL CHECK (execution_status IN ('SUCCESS', 'FAILED', 'PARTIAL')),
    error_message TEXT
);
CREATE INDEX idx_retention_audit_tenant_time ON retention_audit_logs(tenant_id, batch_timestamp DESC);

-- 17. Storage Quarantine Audit
CREATE TABLE storage_quarantine_audit (
    quarantine_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    asset_id UUID,
    upload_id UUID,
    storage_bucket TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    content_sha256 TEXT,
    worm_locked_until TIMESTAMPTZ,
    quarantine_reason TEXT NOT NULL CHECK (quarantine_reason IN ('ORPHANED_AFTER_LOCK', 'CORRUPTED_AFTER_LOCK', 'FAILED_VERIFICATION_LOCKED', 'MANUAL_QUARANTINE')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PURGED_AFTER_EXPIRY')),
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    purged_at TIMESTAMPTZ,
    audit_notes TEXT
);
CREATE INDEX idx_quarantine_audit_tenant ON storage_quarantine_audit(tenant_id, quarantined_at DESC);
CREATE INDEX idx_quarantine_audit_expiry ON storage_quarantine_audit(status, worm_locked_until) WHERE status = 'ACTIVE';


-- ==============================================================================
-- WORM Immutability Functions & Triggers
-- ==============================================================================

CREATE OR REPLACE FUNCTION reject_immutable_update() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR'
           AND pg_has_role(session_user, 'dq_janitor_role', 'MEMBER') THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'table % is strictly immutable (WORM). modifications prohibited', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_snapshot_immutability() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'snapshots are strictly append-only and cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (OLD.version_status = 'ACTIVE' AND NEW.version_status = 'SUPERSEDED')
           OR (OLD.version_status = 'SUPERSEDED' AND NEW.version_status = 'ARCHIVED') THEN
            IF NEW.snapshot_id = OLD.snapshot_id
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.asset_id = OLD.asset_id
               AND NEW.version_number = OLD.version_number
               AND NEW.content_sha256 = OLD.content_sha256
               AND NEW.schema_definition = OLD.schema_definition
               AND NEW.total_rows = OLD.total_rows
               AND NEW.total_columns = OLD.total_columns
               AND NEW.captured_at = OLD.captured_at THEN
                RETURN NEW;
            ELSE
                RAISE EXCEPTION 'metadata payload of snapshot is immutable across status transitions';
            END IF;
        ELSE
            RAISE EXCEPTION 'illegal snapshot state transition from % to %', OLD.version_status, NEW.version_status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_published_result_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR'
           AND pg_has_role(session_user, 'dq_janitor_role', 'MEMBER') THEN
            RETURN OLD;
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM assessments WHERE run_id = OLD.run_id) THEN
        RAISE EXCEPTION 'published result is immutable';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER no_assessment_update BEFORE UPDATE OR DELETE ON assessments
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

CREATE TRIGGER no_dimension_update BEFORE UPDATE OR DELETE ON dimension_results
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

CREATE TRIGGER no_run_event_update BEFORE UPDATE OR DELETE ON run_events
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

CREATE TRIGGER no_audit_log_update BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

CREATE TRIGGER enforce_snapshot_lifecycle BEFORE UPDATE OR DELETE ON dataset_snapshots
    FOR EACH ROW EXECUTE FUNCTION enforce_snapshot_immutability();

CREATE TRIGGER no_published_result_update BEFORE UPDATE OR DELETE ON canonical_quality_results
    FOR EACH ROW EXECUTE FUNCTION reject_published_result_mutation();


-- ==============================================================================
-- Row-Level Security (RLS) & Multi-Tenancy Defense-in-Depth
-- ==============================================================================

-- Enable and Force RLS on all tenant-isolated tables
ALTER TABLE data_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_assets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_data_assets ON data_assets
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE access_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_grants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_access_grants ON access_grants
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE dataset_upload_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_upload_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_upload_sessions ON dataset_upload_sessions
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE dataset_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_dataset_snapshots ON dataset_snapshots
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE canonical_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE canonical_metrics FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_canonical_metrics ON canonical_metrics
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE sensitive_data_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE sensitive_data_findings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_sensitive_findings ON sensitive_data_findings
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE rulesets ENABLE ROW LEVEL SECURITY;
ALTER TABLE rulesets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_rulesets ON rulesets
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE quality_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_quality_rules ON quality_rules
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE data_protection_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_protection_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_data_protection ON data_protection_policies
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE scoring_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE scoring_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_scoring_policies ON scoring_policies
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE evaluation_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_schedules FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_evaluation_schedules ON evaluation_schedules
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);


ALTER TABLE evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_runs ON evaluation_runs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE run_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_run_events ON run_events
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE canonical_quality_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE canonical_quality_results FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_quality_results ON canonical_quality_results
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_assessments ON assessments
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE dimension_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE dimension_results FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_dimension_results ON dimension_results
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE assessment_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_outbox ON assessment_outbox
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);


ALTER TABLE rule_catalog_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE rule_catalog_templates FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_rule_templates ON rule_catalog_templates
    FOR ALL
    USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE ruleset_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE ruleset_templates FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ruleset_templates ON ruleset_templates
    FOR ALL
    USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE scoring_policy_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE scoring_policy_templates FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_policy_templates ON scoring_policy_templates
    FOR ALL
    USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE classification_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE classification_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_classification_rules ON classification_rules
    FOR ALL
    USING (tenant_id IS NULL OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_memberships ON tenant_memberships
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_sessions ON user_sessions
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE user_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_invitations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_invitations ON user_invitations
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);


ALTER TABLE notification_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_channels FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notification_channels ON notification_channels
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE alert_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_subscriptions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_alert_subscriptions ON alert_subscriptions
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE notification_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notification_logs ON notification_logs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE retention_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE retention_audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_retention_audit ON retention_audit_logs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE storage_quarantine_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE storage_quarantine_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_storage_quarantine ON storage_quarantine_audit
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);


-- Cross-tenant dispatcher policies
CREATE POLICY dispatcher_claim_queued_runs ON evaluation_runs
    FOR SELECT
    TO dq_dispatcher_role
    USING (run_status = 'QUEUED');

CREATE POLICY dispatcher_lease_queued_runs ON evaluation_runs
    FOR UPDATE
    TO dq_dispatcher_role
    USING (run_status = 'QUEUED')
    WITH CHECK (run_status IN ('LEASED', 'QUEUED'));

-- Cross-tenant janitor policies
CREATE POLICY janitor_prune_evaluation_runs ON evaluation_runs
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');

CREATE POLICY janitor_prune_quality_results ON canonical_quality_results
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');

CREATE POLICY janitor_prune_assessments ON assessments
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');


-- Grant schema permissions to application and service roles
GRANT ALL ON ALL TABLES IN SCHEMA public TO dq_app_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO dq_app_role;

CREATE POLICY janitor_prune_dimension_results ON dimension_results
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');

CREATE POLICY janitor_prune_run_events ON run_events
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');

CREATE POLICY janitor_prune_outbox ON assessment_outbox
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');

