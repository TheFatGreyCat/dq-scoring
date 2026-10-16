-- ==============================================================================
-- DQ Scoring Engine — Revert Initial Schema (001_initial_schema_down.sql)
-- ==============================================================================

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS storage_quarantine_audit CASCADE;
DROP TABLE IF EXISTS retention_audit_logs CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS notification_logs CASCADE;
DROP TABLE IF EXISTS alert_subscriptions CASCADE;
DROP TABLE IF EXISTS notification_channels CASCADE;
DROP TABLE IF EXISTS assessment_outbox CASCADE;
DROP TABLE IF EXISTS dimension_results CASCADE;
DROP TABLE IF EXISTS assessments CASCADE;
DROP TABLE IF EXISTS canonical_quality_results CASCADE;
DROP TABLE IF EXISTS run_events CASCADE;
DROP TABLE IF EXISTS evaluation_runs CASCADE;
DROP TABLE IF EXISTS evaluation_schedules CASCADE;
DROP TABLE IF EXISTS quality_rules CASCADE;
DROP TABLE IF EXISTS data_protection_policies CASCADE;
DROP TABLE IF EXISTS classification_rules CASCADE;
DROP TABLE IF EXISTS scoring_policies CASCADE;
DROP TABLE IF EXISTS scoring_policy_templates CASCADE;
DROP TABLE IF EXISTS rule_catalog_templates CASCADE;
DROP TABLE IF EXISTS rulesets CASCADE;
DROP TABLE IF EXISTS ruleset_templates CASCADE;
DROP TABLE IF EXISTS sensitive_data_findings CASCADE;
DROP TABLE IF EXISTS canonical_metrics CASCADE;
DROP TABLE IF EXISTS dataset_upload_sessions CASCADE;
DROP TABLE IF EXISTS access_grants CASCADE;
ALTER TABLE IF EXISTS data_assets DROP CONSTRAINT IF EXISTS fk_data_assets_current_snapshot;
DROP TABLE IF EXISTS dataset_snapshots CASCADE;
DROP TABLE IF EXISTS data_assets CASCADE;
DROP TABLE IF EXISTS user_invitations CASCADE;
DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS tenant_memberships CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;

-- Drop functions
DROP FUNCTION IF EXISTS reject_published_result_mutation() CASCADE;
DROP FUNCTION IF EXISTS enforce_snapshot_immutability() CASCADE;
DROP FUNCTION IF EXISTS reject_immutable_update() CASCADE;
DROP FUNCTION IF EXISTS notify_run_queued() CASCADE;

-- Drop roles if needed
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_dispatcher_role') THEN
        DROP ROLE dq_dispatcher_role;
    END IF;
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_janitor_role') THEN
        DROP ROLE dq_janitor_role;
    END IF;
END $$;
