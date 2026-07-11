ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS conflict_group TEXT;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS primary_scoring_rule BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS validation_only BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE dataset_rule_binding ADD COLUMN IF NOT EXISTS conflict_group TEXT;
ALTER TABLE dataset_rule_binding ADD COLUMN IF NOT EXISTS primary_scoring_rule BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE dataset_rule_binding ADD COLUMN IF NOT EXISTS validation_only BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS scan_mode TEXT NOT NULL DEFAULT 'full';
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS sample_method TEXT;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS sample_ratio DOUBLE PRECISION;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS random_seed INTEGER;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS coverage_estimate DOUBLE PRECISION;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS profile_confidence DOUBLE PRECISION;

ALTER TABLE column_profile ADD COLUMN IF NOT EXISTS metric_scope TEXT NOT NULL DEFAULT 'full';
ALTER TABLE column_profile ADD COLUMN IF NOT EXISTS is_approximate BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE column_profile ADD COLUMN IF NOT EXISTS sample_size INTEGER;
ALTER TABLE column_profile ADD COLUMN IF NOT EXISTS sample_ratio DOUBLE PRECISION;
ALTER TABLE column_profile ADD COLUMN IF NOT EXISTS random_seed INTEGER;
ALTER TABLE column_profile ADD COLUMN IF NOT EXISTS coverage_estimate DOUBLE PRECISION;

ALTER TABLE measurement_result ADD COLUMN IF NOT EXISTS measurement_status_reason TEXT;
ALTER TABLE measurement_result ADD COLUMN IF NOT EXISTS validation_scope TEXT NOT NULL DEFAULT 'full';

ALTER TABLE rule_issue_sample ADD COLUMN IF NOT EXISTS rule_code TEXT;

ALTER TABLE score_run ADD COLUMN IF NOT EXISTS policy_snapshot_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE score_run ADD COLUMN IF NOT EXISTS formula_revision TEXT NOT NULL DEFAULT 'scoring_v2';
ALTER TABLE score_run ADD COLUMN IF NOT EXISTS validation_scope TEXT NOT NULL DEFAULT 'full';

ALTER TABLE rule_score_history ADD COLUMN IF NOT EXISTS evaluated_count INTEGER;
ALTER TABLE rule_score_history ADD COLUMN IF NOT EXISTS conflict_group TEXT;
ALTER TABLE rule_score_history ADD COLUMN IF NOT EXISTS primary_scoring_rule BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE rule_score_history ADD COLUMN IF NOT EXISTS score_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE rule_score_history ADD COLUMN IF NOT EXISTS measurement_status_reason TEXT;
ALTER TABLE rule_score_history ADD COLUMN IF NOT EXISTS contribution DOUBLE PRECISION;

ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS measurement_coverage DOUBLE PRECISION;
ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS measured_dimension_count INTEGER;
ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS total_dimension_count INTEGER;
ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS score_status TEXT NOT NULL DEFAULT 'final';
ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS validation_scope TEXT NOT NULL DEFAULT 'full';
ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS policy_snapshot_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE dataset_score_history ADD COLUMN IF NOT EXISTS formula_revision TEXT NOT NULL DEFAULT 'scoring_v2';
