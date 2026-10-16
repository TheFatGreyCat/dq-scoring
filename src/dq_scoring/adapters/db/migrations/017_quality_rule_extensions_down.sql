-- Migration 017 down: Revert quality rule types extension if no new rows exist.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM quality_rules
        WHERE rule_type IN ('TEXT_QUALITY', 'SPELLING', 'JSON_FIELD', 'JSON_ARRAY')
    ) OR EXISTS (
        SELECT 1 FROM rule_catalog_templates
        WHERE rule_type IN ('TEXT_QUALITY', 'SPELLING', 'JSON_FIELD', 'JSON_ARRAY')
    ) THEN
        RAISE EXCEPTION 'Cannot rollback migration 017: rows with extended rule types exist';
    END IF;
END $$;

ALTER TABLE quality_rules
    DROP CONSTRAINT IF EXISTS quality_rules_rule_type_check,
    ADD CONSTRAINT quality_rules_rule_type_check CHECK (
        rule_type IN ('NON_NULL', 'TYPE_PARSE', 'DOMAIN_RANGE', 'UNIQUENESS', 'CROSS_FIELD')
    );

ALTER TABLE rule_catalog_templates
    DROP CONSTRAINT IF EXISTS rule_catalog_templates_rule_type_check,
    ADD CONSTRAINT rule_catalog_templates_rule_type_check CHECK (
        rule_type IN ('NON_NULL', 'TYPE_PARSE', 'DOMAIN_RANGE', 'UNIQUENESS', 'CROSS_FIELD')
    );
