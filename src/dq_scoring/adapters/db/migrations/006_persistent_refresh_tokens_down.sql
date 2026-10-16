-- Revert migration 006: drop persistent refresh-token families.
DROP TABLE IF EXISTS refresh_tokens;
