CREATE TABLE IF NOT EXISTS rule_recommendation_run (
    recommendation_run_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
    profile_fingerprint TEXT,
    catalog_revision TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rule_recommendation_result (
    recommendation_id TEXT PRIMARY KEY,
    recommendation_run_id TEXT NOT NULL REFERENCES rule_recommendation_run(recommendation_run_id),
    column_id TEXT,
    rule_template_id TEXT NOT NULL REFERENCES rule_template(rule_template_id),
    target_columns TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    candidate_score DOUBLE PRECISION NOT NULL,
    score_components_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score_margin DOUBLE PRECISION,
    ambiguity_status TEXT NOT NULL CHECK (ambiguity_status IN ('clear', 'moderate', 'ambiguous')),
    decision TEXT NOT NULL DEFAULT 'suggested' CHECK (decision IN ('suggested', 'accepted', 'rejected', 'edited')),
    reviewed_at TIMESTAMPTZ,
    suggested_parameters_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    source TEXT NOT NULL DEFAULT 'framework_auto',
    editable BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rule_recommendation_result_run ON rule_recommendation_result(recommendation_run_id);
CREATE INDEX IF NOT EXISTS idx_rule_recommendation_result_decision ON rule_recommendation_result(decision);