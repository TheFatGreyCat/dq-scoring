-- Run only after API/workers of the new version are stopped and code is rolled back together.
DROP INDEX idx_runs_completed_evaluation_fingerprint;
ALTER TABLE evaluation_runs DROP COLUMN evaluation_fingerprint;
