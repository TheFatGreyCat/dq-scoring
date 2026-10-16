-- ==============================================================================
-- Migration 003: Harden role isolation by revoking service roles from dq_app_role
-- ==============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        JOIN pg_catalog.pg_roles r1 ON m.roleid = r1.oid
        JOIN pg_catalog.pg_roles r2 ON m.member = r2.oid
        WHERE r1.rolname = 'dq_dispatcher_role' AND r2.rolname = 'dq_app_role'
    ) THEN
        REVOKE dq_dispatcher_role FROM dq_app_role;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        JOIN pg_catalog.pg_roles r1 ON m.roleid = r1.oid
        JOIN pg_catalog.pg_roles r2 ON m.member = r2.oid
        WHERE r1.rolname = 'dq_janitor_role' AND r2.rolname = 'dq_app_role'
    ) THEN
        REVOKE dq_janitor_role FROM dq_app_role;
    END IF;
END $$;
