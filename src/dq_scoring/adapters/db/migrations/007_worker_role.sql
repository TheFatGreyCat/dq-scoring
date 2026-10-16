-- Migration 007: least-privilege group role for evaluation workers.
-- Workers claim QUEUED runs across tenants (dq_dispatcher_role policies) and then write
-- results under the run's tenant context (dq_app_role policies). Operators create the
-- LOGIN separately so no credential lives in migrations:
--   CREATE ROLE dq_worker_user LOGIN PASSWORD '<secret>' NOSUPERUSER NOBYPASSRLS IN ROLE dq_worker_role;
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dq_worker_role') THEN
        CREATE ROLE dq_worker_role NOLOGIN NOSUPERUSER NOBYPASSRLS INHERIT;
    END IF;
END $$;

GRANT dq_dispatcher_role TO dq_worker_role;
GRANT dq_app_role TO dq_worker_role;
