SET LOCAL row_security=off;
LOCK TABLE snapshot_semantic_state, snapshot_column_semantics, snapshot_column_semantic_history IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM snapshot_semantic_state)
       OR EXISTS (SELECT 1 FROM snapshot_column_semantics)
       OR EXISTS (SELECT 1 FROM snapshot_column_semantic_history) THEN
        RAISE EXCEPTION 'SEMANTIC_EVIDENCE_NOT_EMPTY';
    END IF;
END $$;
DROP TABLE snapshot_column_semantic_history;
DROP TABLE snapshot_column_semantics;
DROP TABLE snapshot_semantic_state;
DROP FUNCTION enforce_semantic_revision();
DROP FUNCTION enforce_semantic_history();
DROP FUNCTION enforce_semantic_projection();
DROP FUNCTION check_semantic_commit();
