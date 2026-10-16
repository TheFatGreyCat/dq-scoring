-- ==============================================================================
-- Migration 004: Add created_by to rulesets and scoring_policies for 4-eyes governance
-- ==============================================================================

ALTER TABLE rulesets ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(user_id);
UPDATE rulesets SET created_by = submitted_by WHERE created_by IS NULL;
ALTER TABLE rulesets ALTER COLUMN created_by SET NOT NULL;

ALTER TABLE scoring_policies ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(user_id);
UPDATE scoring_policies SET created_by = submitted_by WHERE created_by IS NULL;
ALTER TABLE scoring_policies ALTER COLUMN created_by SET NOT NULL;
