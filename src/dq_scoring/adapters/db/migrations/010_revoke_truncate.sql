-- Migration 010: TRUNCATE bypasses WORM row triggers and RLS, so no service role may use it.
-- dq_worker_role inherits from dq_app_role. Superuser test cleanup is unaffected.
REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM dq_app_role, dq_dispatcher_role, dq_janitor_role, dq_public_role;
