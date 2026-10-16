-- ==============================================================================
-- Migration 003 Down: Re-grant dispatcher and janitor roles to dq_app_role
-- ==============================================================================

GRANT dq_dispatcher_role TO dq_app_role;
GRANT dq_janitor_role TO dq_app_role;
