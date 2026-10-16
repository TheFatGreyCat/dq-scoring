-- ==============================================================================
-- Migration 002: Harden dispatcher claim/lease policies and role table permissions
-- ==============================================================================

-- 1. Update evaluation_runs dispatcher policies to allow claiming expired leases
DROP POLICY IF EXISTS dispatcher_claim_queued_runs ON evaluation_runs;
DROP POLICY IF EXISTS dispatcher_lease_queued_runs ON evaluation_runs;

CREATE POLICY dispatcher_claim_queued_runs ON evaluation_runs
    FOR SELECT
    TO dq_dispatcher_role
    USING (run_status IN ('QUEUED', 'LEASED', 'RUNNING'));

CREATE POLICY dispatcher_lease_queued_runs ON evaluation_runs
    FOR UPDATE
    TO dq_dispatcher_role
    USING (
        run_status = 'QUEUED'
        OR (run_status IN ('LEASED', 'RUNNING') AND lease_expires_at < now())
    )
    WITH CHECK (run_status IN ('LEASED', 'QUEUED'));

-- 2. Explicit table permissions for dq_dispatcher_role
GRANT SELECT, UPDATE ON evaluation_runs TO dq_dispatcher_role;
GRANT INSERT ON run_events TO dq_dispatcher_role;
GRANT SELECT ON tenants, users, data_assets, dataset_snapshots, rulesets, quality_rules, scoring_policies TO dq_dispatcher_role;

-- 3. Explicit table permissions for dq_janitor_role
GRANT SELECT, DELETE ON evaluation_runs, canonical_quality_results TO dq_janitor_role;
GRANT SELECT, INSERT ON retention_audit_logs TO dq_janitor_role;
