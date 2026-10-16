-- Revert migration 010 (001 granted ALL, including TRUNCATE, to dq_app_role only).
GRANT TRUNCATE ON ALL TABLES IN SCHEMA public TO dq_app_role;
