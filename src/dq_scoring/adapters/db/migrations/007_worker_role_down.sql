-- Revert migration 007: remove the worker group role.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_worker_role') THEN
        REVOKE dq_dispatcher_role FROM dq_worker_role;
        REVOKE dq_app_role FROM dq_worker_role;
        DROP ROLE dq_worker_role;
    END IF;
END $$;
