-- Rollback migration 019: Sensitive data findings counters and asset protection policy revisions

LOCK TABLE sensitive_data_findings IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE asset_protection_revisions IN SHARE ROW EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM sensitive_data_findings
        WHERE matched_count > 0 OR observed_count > 0 OR detector_code IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Refusing to revert migration 019: sensitive_data_findings contains detector records with counters';
    END IF;

    IF EXISTS (
        SELECT 1 FROM asset_protection_revisions
        WHERE version > 0 OR jsonb_array_length(extra_columns) > 0
    ) THEN
        RAISE EXCEPTION 'Refusing to revert migration 019: asset_protection_revisions contains active revisions';
    END IF;
END $$;

DROP TABLE IF EXISTS asset_protection_revisions CASCADE;
DROP INDEX IF EXISTS uq_findings_detector;

ALTER TABLE sensitive_data_findings
    DROP COLUMN IF EXISTS path,
    DROP COLUMN IF EXISTS detector_code,
    DROP COLUMN IF EXISTS detector_revision,
    DROP COLUMN IF EXISTS matched_count,
    DROP COLUMN IF EXISTS observed_count,
    DROP COLUMN IF EXISTS detection_method;

-- Restore legacy user_role check on data_protection_policies
ALTER TABLE data_protection_policies DROP CONSTRAINT IF EXISTS data_protection_policies_user_role_check;
ALTER TABLE data_protection_policies ADD CONSTRAINT data_protection_policies_user_role_check
    CHECK (user_role IN ('DATA_OWNER', 'DATA_STEWARD', 'COMPLIANCE_AUDITOR', 'VIEWER_UNPRIVILEGED'));
