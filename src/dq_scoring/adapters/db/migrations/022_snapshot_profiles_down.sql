SET LOCAL row_security=off;
LOCK TABLE snapshot_profile_jobs IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM snapshot_profile_jobs) THEN
        RAISE EXCEPTION 'PROFILE_EVIDENCE_NOT_EMPTY';
    END IF;
END $$;
DROP TABLE snapshot_profile_jobs;
DROP FUNCTION enforce_snapshot_profile_transition();
DROP FUNCTION snapshot_profile_fingerprint(UUID,UUID,JSONB,JSONB,TEXT);
