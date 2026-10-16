-- Migration 008: persist the domain-computed values the API used to approximate.
-- dimension_results.coverage_ratio: weighted coverage C_d (DQ_SCORING_THEORY §11.1);
--   NULL when no rule was expected, and for rows written before this migration.
-- canonical_quality_results.violations_count: domain violations (includes missing under
--   null_policy 'fail'); NULL for rows written before this migration.
ALTER TABLE dimension_results
    ADD COLUMN coverage_ratio REAL CHECK (coverage_ratio IS NULL OR coverage_ratio BETWEEN 0 AND 1);
ALTER TABLE canonical_quality_results
    ADD COLUMN violations_count BIGINT CHECK (violations_count IS NULL OR violations_count >= 0);

GRANT SELECT (coverage_ratio) ON dimension_results TO dq_public_role;
