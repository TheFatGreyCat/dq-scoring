-- Migration 025: semantic evaluation fingerprint for reusing completed, published runs.
-- Nullable and never backfilled: legacy runs lack a stable identity. assessment/config hashes are untouched.
ALTER TABLE evaluation_runs
    ADD COLUMN evaluation_fingerprint TEXT CHECK (evaluation_fingerprint ~ '^[0-9a-f]{64}$');

CREATE INDEX idx_runs_completed_evaluation_fingerprint
    ON evaluation_runs (tenant_id, created_by, evaluation_fingerprint, completed_at DESC)
    WHERE run_status = 'SUCCEEDED' AND evaluation_fingerprint IS NOT NULL;
