ALTER TABLE ruleset_templates
    ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    ADD COLUMN provenance JSONB NOT NULL DEFAULT '{"kind":"LEGACY_UNVERIFIED"}'::jsonb,
    ADD COLUMN examples JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN placeholder_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN payload_sha256 CHAR(64),
    ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','PENDING_APPROVAL','ACTIVE','DEPRECATED')),
    ADD COLUMN created_by UUID REFERENCES users(user_id),
    ADD COLUMN submitted_by UUID REFERENCES users(user_id),
    ADD COLUMN approved_by UUID REFERENCES users(user_id),
    ADD COLUMN submitted_at TIMESTAMPTZ,
    ADD COLUMN approved_at TIMESTAMPTZ;
DROP INDEX uq_ruleset_template_code_scope;
CREATE UNIQUE INDEX uq_ruleset_template_revision_scope ON ruleset_templates(COALESCE(tenant_id,'00000000-0000-0000-0000-000000000000'::uuid),template_code,revision);
CREATE UNIQUE INDEX uq_ruleset_template_active_scope ON ruleset_templates(COALESCE(tenant_id,'00000000-0000-0000-0000-000000000000'::uuid),template_code) WHERE status='ACTIVE';
