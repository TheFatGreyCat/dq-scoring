-- Rollback migration 021: refuses when generated narrative reports would be lost.
LOCK TABLE assessment_narratives IN SHARE ROW EXCLUSIVE MODE;

SET LOCAL row_security = off;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM assessment_narratives) THEN
        RAISE EXCEPTION 'Refusing to revert migration 021: assessment_narratives contains reports';
    END IF;
END $$;

DROP TABLE IF EXISTS assessment_narratives;
