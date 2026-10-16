LOCK TABLE ruleset_templates IN SHARE ROW EXCLUSIVE MODE;
DO $$ BEGIN
IF EXISTS (
    SELECT 1 FROM ruleset_templates
    WHERE revision > 1 OR status <> 'ACTIVE' OR provenance <> '{"kind":"LEGACY_UNVERIFIED"}'::jsonb OR examples <> '[]'::jsonb
       OR placeholder_schema <> '{}'::jsonb OR payload_sha256 IS NOT NULL OR created_by IS NOT NULL OR submitted_by IS NOT NULL
       OR approved_by IS NOT NULL OR submitted_at IS NOT NULL OR approved_at IS NOT NULL
) THEN
RAISE EXCEPTION 'Cannot rollback 018: versioned or governed template data exists';
END IF;
END $$;
DROP INDEX uq_ruleset_template_active_scope;
DROP INDEX uq_ruleset_template_revision_scope;
ALTER TABLE ruleset_templates DROP COLUMN revision, DROP COLUMN provenance, DROP COLUMN examples, DROP COLUMN placeholder_schema, DROP COLUMN payload_sha256, DROP COLUMN status, DROP COLUMN created_by, DROP COLUMN submitted_by, DROP COLUMN approved_by, DROP COLUMN submitted_at, DROP COLUMN approved_at;
CREATE UNIQUE INDEX uq_ruleset_template_code_scope ON ruleset_templates(COALESCE(tenant_id,'00000000-0000-0000-0000-000000000000'::uuid),template_code);
