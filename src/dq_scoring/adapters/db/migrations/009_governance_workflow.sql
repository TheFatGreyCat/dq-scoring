-- Migration 009: explicit approval workflow and persisted names for rulesets/policies.
-- DRAFT -> PENDING_APPROVAL (submit) -> ACTIVE (independent approval) -> DEPRECATED (superseded).
-- submitted_by/submitted_at are now set by the submit step instead of at creation.
-- Existing rows keep their values; their names stay NULL (the API falls back to version).

ALTER TABLE rulesets
    ADD COLUMN name TEXT,
    ADD COLUMN created_at TIMESTAMPTZ;
UPDATE rulesets SET created_at = submitted_at WHERE created_at IS NULL;
ALTER TABLE rulesets
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN submitted_by DROP NOT NULL,
    ALTER COLUMN submitted_at DROP NOT NULL,
    DROP CONSTRAINT rulesets_status_check,
    ADD CONSTRAINT rulesets_status_check
        CHECK (status IN ('DRAFT', 'PENDING_APPROVAL', 'ACTIVE', 'DEPRECATED')),
    ADD CONSTRAINT rulesets_submission_check
        CHECK (status NOT IN ('PENDING_APPROVAL', 'ACTIVE')
               OR (submitted_by IS NOT NULL AND submitted_at IS NOT NULL));

ALTER TABLE scoring_policies
    ADD COLUMN name TEXT,
    ADD COLUMN created_at TIMESTAMPTZ;
UPDATE scoring_policies SET created_at = submitted_at WHERE created_at IS NULL;
ALTER TABLE scoring_policies
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN submitted_by DROP NOT NULL,
    ALTER COLUMN submitted_at DROP NOT NULL,
    DROP CONSTRAINT scoring_policies_status_check,
    ADD CONSTRAINT scoring_policies_status_check
        CHECK (status IN ('DRAFT', 'PENDING_APPROVAL', 'ACTIVE', 'DEPRECATED')),
    ADD CONSTRAINT scoring_policies_submission_check
        CHECK (status NOT IN ('PENDING_APPROVAL', 'ACTIVE')
               OR (submitted_by IS NOT NULL AND submitted_at IS NOT NULL));
