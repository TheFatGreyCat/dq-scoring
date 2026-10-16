-- Remove tenant API bootstrap and public projection policies.
DROP POLICY IF EXISTS public_dimension_results_read ON dimension_results;
DROP POLICY IF EXISTS public_assessment_read ON assessments;
DROP POLICY IF EXISTS tenant_membership_user_access ON tenant_memberships;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_public_role') THEN
        REVOKE ALL ON assessments FROM dq_public_role;
        REVOKE ALL ON dimension_results FROM dq_public_role;
        REVOKE USAGE ON SCHEMA public FROM dq_public_role;
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_auth_members m
            JOIN pg_catalog.pg_roles r1 ON m.roleid = r1.oid
            JOIN pg_catalog.pg_roles r2 ON m.member = r2.oid
            WHERE r1.rolname = 'dq_public_role' AND r2.rolname = 'dq_app_role'
        ) THEN
            REVOKE dq_public_role FROM dq_app_role;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_auth_members m
            JOIN pg_catalog.pg_roles r1 ON m.roleid = r1.oid
            JOIN pg_catalog.pg_roles r2 ON m.member = r2.oid
            WHERE r1.rolname = 'dq_public_role' AND r2.rolname = CURRENT_USER
        ) THEN
            REVOKE dq_public_role FROM CURRENT_USER;
        END IF;
        DROP ROLE dq_public_role;
    END IF;
END $$;
