-- ==============================================================================
-- Rollback Migration 002: Revert dispatcher claim/lease policies and permissions
-- ==============================================================================

DROP POLICY IF EXISTS dispatcher_claim_queued_runs ON evaluation_runs;
DROP POLICY IF EXISTS dispatcher_lease_queued_runs ON evaluation_runs;

CREATE POLICY dispatcher_claim_queued_runs ON evaluation_runs
    FOR SELECT
    TO dq_dispatcher_role
    USING (run_status = 'QUEUED');

CREATE POLICY dispatcher_lease_queued_runs ON evaluation_runs
    FOR UPDATE
    TO dq_dispatcher_role
    USING (run_status = 'QUEUED')
    WITH CHECK (run_status IN ('LEASED', 'QUEUED'));

REVOKE SELECT, UPDATE ON evaluation_runs FROM dq_dispatcher_role;
REVOKE INSERT ON run_events FROM dq_dispatcher_role;
REVOKE SELECT ON tenants, users, data_assets, dataset_snapshots, rulesets, quality_rules, scoring_policies FROM dq_dispatcher_role;

REVOKE SELECT, DELETE ON evaluation_runs, canonical_quality_results FROM dq_janitor_role;
REVOKE SELECT, INSERT ON retention_audit_logs FROM dq_janitor_role;
