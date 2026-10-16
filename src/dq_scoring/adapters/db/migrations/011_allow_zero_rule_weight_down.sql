-- Revert migration 011 (zero weights become 1.0 again, as the API stored them before).
ALTER TABLE quality_rules
    DROP CONSTRAINT quality_rules_advisory_weight_check,
    DROP CONSTRAINT quality_rules_weight_check;
UPDATE quality_rules SET weight = 1.0 WHERE weight = 0;
ALTER TABLE quality_rules ADD CONSTRAINT quality_rules_weight_check CHECK (weight > 0);
