-- Migration 012: emails are unique and looked up case-insensitively (login uses lower(email)).
-- Fails if case-variant duplicates already exist; merge or rename those accounts by hand first.
CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));
DROP INDEX IF EXISTS idx_users_email;
