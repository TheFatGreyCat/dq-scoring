-- Rollback migration 020: privacy workspace.
-- Only objects created by 020 are removed; refuses when user-authored privacy data would be lost.
-- Migrated explicit protected columns are restored into asset_protection_revisions.extra_columns.

LOCK TABLE sensitive_data_findings IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE asset_column_classifications IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE privacy_change_events IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE privacy_detector_rules IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE privacy_scan_jobs IN SHARE ROW EXCLUSIVE MODE;

SET LOCAL row_security = off;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM privacy_change_events) THEN
        RAISE EXCEPTION 'Refusing to revert migration 020: privacy_change_events contains audit history';
    END IF;

    IF EXISTS (
        SELECT 1 FROM asset_column_classifications
        WHERE reason <> 'Migrated explicit protected column'
    ) THEN
        RAISE EXCEPTION 'Refusing to revert migration 020: asset_column_classifications contains user declarations';
    END IF;

    IF EXISTS (SELECT 1 FROM privacy_detector_rules WHERE kind <> 'BUILTIN' OR revision > 1) THEN
        RAISE EXCEPTION 'Refusing to revert migration 020: privacy_detector_rules contains user revisions';
    END IF;

    IF EXISTS (SELECT 1 FROM privacy_scan_jobs) THEN
        RAISE EXCEPTION 'Refusing to revert migration 020: privacy_scan_jobs contains scans';
    END IF;

    IF EXISTS (
        SELECT 1 FROM sensitive_data_findings
        WHERE review_reason IS NOT NULL OR reviewed_by IS NOT NULL OR reviewed_at IS NOT NULL
           OR privacy_rule_revision IS NOT NULL OR scan_id IS NOT NULL
           OR detection_method = 'CUSTOM_PATTERN'
    ) THEN
        RAISE EXCEPTION 'Refusing to revert migration 020: sensitive_data_findings contains privacy workspace data';
    END IF;
END $$;

DROP INDEX IF EXISTS uq_findings_scan_rule;
DROP INDEX uq_findings_detector;
CREATE UNIQUE INDEX uq_findings_detector ON sensitive_data_findings
    (tenant_id,snapshot_id,column_name,path,detector_code,detector_revision)
    WHERE detector_code IS NOT NULL;
REVOKE UPDATE ON asset_protection_revisions FROM dq_worker_role;

ALTER TABLE sensitive_data_findings DROP CONSTRAINT IF EXISTS sensitive_data_findings_detection_method_check;
ALTER TABLE sensitive_data_findings ADD CONSTRAINT sensitive_data_findings_detection_method_check
    CHECK (detection_method IS NULL OR detection_method IN ('VALUE_PATTERN', 'COLUMN_NAME', 'LEGACY'));

ALTER TABLE sensitive_data_findings
    DROP CONSTRAINT IF EXISTS fk_findings_privacy_scan,
    DROP CONSTRAINT IF EXISTS fk_findings_privacy_rule,
    DROP CONSTRAINT IF EXISTS chk_findings_privacy_rule_identity,
    DROP COLUMN IF EXISTS scan_id,
    DROP COLUMN IF EXISTS privacy_rule_revision,
    DROP COLUMN IF EXISTS reviewed_at,
    DROP COLUMN IF EXISTS reviewed_by,
    DROP COLUMN IF EXISTS review_reason;

DROP TABLE IF EXISTS privacy_scan_jobs;
DROP TABLE IF EXISTS privacy_detector_rules;
DROP FUNCTION IF EXISTS enforce_privacy_rule_revision();
DROP TABLE IF EXISTS privacy_detector_configs;
DROP TABLE IF EXISTS privacy_change_events;

ALTER TABLE asset_protection_revisions ADD COLUMN extra_columns JSONB NOT NULL DEFAULT '[]'::jsonb;
UPDATE asset_protection_revisions r
SET extra_columns = m.cols
FROM (
    SELECT tenant_id, asset_id, jsonb_agg(column_name ORDER BY column_name) AS cols
    FROM asset_column_classifications
    GROUP BY tenant_id, asset_id
) m
WHERE m.tenant_id = r.tenant_id AND m.asset_id = r.asset_id;

DROP TABLE IF EXISTS asset_column_classifications;
