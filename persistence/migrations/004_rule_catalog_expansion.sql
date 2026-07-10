CREATE TABLE IF NOT EXISTS rule_fixture_manifest (
    rule_code TEXT NOT NULL,
    revision INTEGER NOT NULL,
    fixture_kind TEXT NOT NULL CHECK (fixture_kind IN ('positive', 'negative', 'edge')),
    fixture_path TEXT NOT NULL,
    expected_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_code, revision, fixture_kind)
);