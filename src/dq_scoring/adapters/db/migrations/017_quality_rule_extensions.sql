-- Migration 017: Extend quality rule types with text quality, spelling, and semi-structured rules.

ALTER TABLE quality_rules
    DROP CONSTRAINT IF EXISTS quality_rules_rule_type_check,
    ADD CONSTRAINT quality_rules_rule_type_check CHECK (
        rule_type IN (
            'NON_NULL', 'TYPE_PARSE', 'DOMAIN_RANGE', 'UNIQUENESS', 'CROSS_FIELD',
            'TEXT_QUALITY', 'SPELLING', 'JSON_FIELD', 'JSON_ARRAY'
        )
    );

ALTER TABLE rule_catalog_templates
    DROP CONSTRAINT IF EXISTS rule_catalog_templates_rule_type_check,
    ADD CONSTRAINT rule_catalog_templates_rule_type_check CHECK (
        rule_type IN (
            'NON_NULL', 'TYPE_PARSE', 'DOMAIN_RANGE', 'UNIQUENESS', 'CROSS_FIELD',
            'TEXT_QUALITY', 'SPELLING', 'JSON_FIELD', 'JSON_ARRAY'
        )
    );
