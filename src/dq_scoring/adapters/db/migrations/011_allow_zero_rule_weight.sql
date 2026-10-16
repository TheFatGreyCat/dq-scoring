-- Migration 011: a rule weight of 0 means "excluded from the score" (core treats weight <= 0 that way),
-- so store 0 instead of rewriting it to 1.0. Advisory rules never contribute, so their weight must be 0.
UPDATE quality_rules SET weight = 0 WHERE is_advisory;
ALTER TABLE quality_rules
    DROP CONSTRAINT quality_rules_weight_check,
    ADD CONSTRAINT quality_rules_weight_check CHECK (weight >= 0),
    ADD CONSTRAINT quality_rules_advisory_weight_check CHECK (NOT is_advisory OR weight = 0);
