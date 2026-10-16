-- Migration 005: RLS policies for tenant API access, user login, and public read


DROP POLICY IF EXISTS tenant_membership_user_access ON tenant_memberships;
CREATE POLICY tenant_membership_user_access ON tenant_memberships
    FOR SELECT
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID);

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_public_role') THEN
        CREATE ROLE dq_public_role NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO dq_public_role;

GRANT dq_public_role TO CURRENT_USER;
GRANT dq_public_role TO dq_app_role WITH INHERIT FALSE, SET TRUE;

REVOKE ALL ON assessments FROM dq_public_role;
REVOKE ALL ON dimension_results FROM dq_public_role;

GRANT SELECT (
    assessment_id,
    dq_score,
    publication_status,
    visibility_scope,
    coverage_ratio,
    quality_gate,
    assessment_hash,
    published_at
) ON assessments TO dq_public_role;

GRANT SELECT (
    assessment_id,
    dimension,
    dimension_score,
    total_rules,
    measured_rules
) ON dimension_results TO dq_public_role;

DROP POLICY IF EXISTS public_assessment_read ON assessments;
CREATE POLICY public_assessment_read ON assessments
    FOR SELECT
    TO dq_public_role
    USING (publication_status = 'PUBLISHED' AND visibility_scope = 'PUBLIC_READ');

DROP POLICY IF EXISTS public_dimension_results_read ON dimension_results;
CREATE POLICY public_dimension_results_read ON dimension_results
    FOR SELECT
    TO dq_public_role
    USING (
        EXISTS (
            SELECT 1 FROM assessments a
            WHERE a.assessment_id = dimension_results.assessment_id
              AND a.publication_status = 'PUBLISHED'
              AND a.visibility_scope = 'PUBLIC_READ'
        )
    );
