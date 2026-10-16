-- Revert migration 012.
CREATE INDEX idx_users_email ON users(email);
DROP INDEX uq_users_email_lower;
