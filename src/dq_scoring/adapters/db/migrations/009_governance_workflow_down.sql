-- Revert migration 009 (fails if PENDING_APPROVAL rows or unsubmitted rows exist; resolve them first).
ALTER TABLE scoring_policies
    DROP CONSTRAINT scoring_policies_submission_check,
    DROP CONSTRAINT scoring_policies_status_check,
    ADD CONSTRAINT scoring_policies_status_check CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')),
    ALTER COLUMN submitted_at SET NOT NULL,
    ALTER COLUMN submitted_by SET NOT NULL,
    DROP COLUMN created_at,
    DROP COLUMN name;
ALTER TABLE rulesets
    DROP CONSTRAINT rulesets_submission_check,
    DROP CONSTRAINT rulesets_status_check,
    ADD CONSTRAINT rulesets_status_check CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')),
    ALTER COLUMN submitted_at SET NOT NULL,
    ALTER COLUMN submitted_by SET NOT NULL,
    DROP COLUMN created_at,
    DROP COLUMN name;
