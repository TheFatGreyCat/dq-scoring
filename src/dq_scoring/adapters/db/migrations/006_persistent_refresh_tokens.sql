-- Migration 006: persistent refresh-token families (AC-023) shared by all API processes.
-- Only the SHA-256 of each opaque token is stored. No tenant RLS: a refresh request has
-- no tenant context, and possession of the raw token is the credential being checked.

CREATE TABLE refresh_tokens (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    family_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > issued_at)
);

CREATE INDEX idx_refresh_tokens_family ON refresh_tokens(family_id);

GRANT SELECT, INSERT, UPDATE ON refresh_tokens TO dq_app_role;
