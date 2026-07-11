ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS chunk_size INTEGER;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS memory_budget_mb INTEGER;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS time_budget_sec INTEGER;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS budget_used JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS skipped_metrics TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS termination_reason TEXT;
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS deep_profiled_columns TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE profiling_run ADD COLUMN IF NOT EXISTS profile_strategy TEXT NOT NULL DEFAULT 'dataframe_full';