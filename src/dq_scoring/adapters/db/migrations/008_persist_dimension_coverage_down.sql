-- Revert migration 008.
ALTER TABLE canonical_quality_results DROP COLUMN IF EXISTS violations_count;
ALTER TABLE dimension_results DROP COLUMN IF EXISTS coverage_ratio;
