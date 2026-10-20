-- Migration 021: Advisory assessment narratives.
-- Append-only reports kept apart from the immutable assessment; the assessment and its hash are untouched.

CREATE TABLE assessment_narratives (
    report_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    assessment_id UUID NOT NULL,
    assessment_hash TEXT NOT NULL CHECK (char_length(assessment_hash) BETWEEN 1 AND 128),
    requested_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    narrative TEXT NOT NULL CHECK (char_length(narrative) BETWEEN 1 AND 4000),
    cited_rules JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(cited_rules) = 'array' AND jsonb_array_length(cited_rules) <= 100),
    model TEXT NOT NULL CHECK (char_length(model) BETWEEN 1 AND 128),
    prompt_version TEXT NOT NULL CHECK (char_length(prompt_version) BETWEEN 1 AND 64),
    context_sha256 TEXT NOT NULL CHECK (context_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, report_id),
    FOREIGN KEY (tenant_id, assessment_id) REFERENCES assessments(tenant_id, assessment_id) ON DELETE CASCADE
);
CREATE INDEX idx_assessment_narratives_latest
    ON assessment_narratives(tenant_id, assessment_id, created_at DESC, report_id DESC);

CREATE TRIGGER no_assessment_narrative_update BEFORE UPDATE OR DELETE ON assessment_narratives
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

ALTER TABLE assessment_narratives ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_narratives FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_assessment_narratives ON assessment_narratives
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

-- Retention pruning of an assessment cascades to its narratives under the same janitor authorization.
CREATE POLICY janitor_prune_assessment_narratives ON assessment_narratives
    FOR ALL
    TO dq_janitor_role
    USING (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR')
    WITH CHECK (NULLIF(current_setting('app.retention_execution', true), '') = 'AUTHORIZED_RETENTION_JANITOR');

GRANT SELECT, INSERT ON assessment_narratives TO dq_app_role;
GRANT SELECT, DELETE ON assessment_narratives TO dq_janitor_role;
