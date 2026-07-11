CREATE TABLE IF NOT EXISTS dataset (
    dataset_id TEXT PRIMARY KEY,
    dataset_name TEXT,
    dataset_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_version (
    dataset_version_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES dataset(dataset_id),
    version_label TEXT NOT NULL,
    source_fingerprint TEXT,
    row_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset_column (
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
    column_name TEXT NOT NULL,
    ordinal_position INTEGER NOT NULL,
    declared_data_type TEXT,
    inferred_data_type TEXT,
    nullable BOOLEAN,
    semantic_type TEXT,
    semantic_confidence DOUBLE PRECISION,
    is_business_key BOOLEAN NOT NULL DEFAULT false,
    is_cde BOOLEAN NOT NULL DEFAULT false,
    is_mandatory BOOLEAN NOT NULL DEFAULT false,
    is_identifier BOOLEAN NOT NULL DEFAULT false,
    is_timestamp BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (dataset_version_id, column_name)
);

CREATE TABLE IF NOT EXISTS rule_template (
    rule_template_id TEXT PRIMARY KEY,
    rule_code TEXT NOT NULL,
    rule_template_version INTEGER NOT NULL,
    rule_category TEXT NOT NULL CHECK (rule_category IN ('general', 'business', 'technical')),
    dimension TEXT NOT NULL,
    management_scope TEXT NOT NULL,
    target_scope TEXT NOT NULL,
    evaluation_scope TEXT NOT NULL,
    operator TEXT NOT NULL,
    applicability JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalization JSONB NOT NULL DEFAULT '{}'::jsonb,
    null_policy TEXT NOT NULL,
    accuracy_mode TEXT,
    default_acceptance DOUBLE PRECISION,
    default_scoring_threshold DOUBLE PRECISION,
    default_severity TEXT NOT NULL,
    base_rule_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    score_enabled BOOLEAN NOT NULL DEFAULT true,
    gate_enabled BOOLEAN NOT NULL DEFAULT false,
    scoring_method TEXT NOT NULL,
    locked BOOLEAN NOT NULL DEFAULT true,
    active BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (rule_code, rule_template_version)
);

CREATE TABLE IF NOT EXISTS dataset_rule_binding (
    binding_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
    rule_template_id TEXT NOT NULL REFERENCES rule_template(rule_template_id),
    target_columns TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    acceptance_threshold DOUBLE PRECISION,
    scoring_pass_threshold DOUBLE PRECISION,
    severity TEXT NOT NULL,
    backend TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    recommendation_confidence DOUBLE PRECISION,
    applicability_status TEXT NOT NULL,
    exception_reason TEXT,
    score_enabled BOOLEAN NOT NULL DEFAULT true,
    gate_enabled BOOLEAN NOT NULL DEFAULT false,
    scoring_method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiling_run (
    profiling_run_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS dataset_profile (
    profiling_run_id TEXT PRIMARY KEY REFERENCES profiling_run(profiling_run_id),
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    duplicate_row_count INTEGER NOT NULL,
    duplicate_row_ratio DOUBLE PRECISION NOT NULL,
    profile_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS column_profile (
    profiling_run_id TEXT NOT NULL REFERENCES profiling_run(profiling_run_id),
    column_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value JSONB,
    metric_source TEXT NOT NULL CHECK (metric_source IN ('pandas', 'gx')),
    gx_expectation_type TEXT,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (profiling_run_id, column_name, metric_name, metric_source)
);

CREATE TABLE IF NOT EXISTS validation_run (
    validation_run_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
    ruleset_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS measurement_result (
    measurement_result_id TEXT PRIMARY KEY,
    validation_run_id TEXT NOT NULL REFERENCES validation_run(validation_run_id),
    binding_id TEXT NOT NULL REFERENCES dataset_rule_binding(binding_id),
    evaluation_unit TEXT NOT NULL,
    expectation_success BOOLEAN,
    measurement_status TEXT NOT NULL,
    observed_value_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_spec_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    failure_breakdown_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    backend TEXT NOT NULL,
    execution_time_ms INTEGER,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS record_measurement_summary (
    measurement_result_id TEXT PRIMARY KEY REFERENCES measurement_result(measurement_result_id),
    passed_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    missing_count INTEGER NOT NULL,
    not_applicable_count INTEGER NOT NULL,
    records_in_scope INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_issue_sample (
    validation_run_id TEXT NOT NULL REFERENCES validation_run(validation_run_id),
    binding_id TEXT NOT NULL REFERENCES dataset_rule_binding(binding_id),
    record_key TEXT,
    target_column TEXT,
    actual_value TEXT,
    expected_condition TEXT,
    issue_type TEXT,
    sampled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scoring_policy (
    scoring_policy_id TEXT PRIMARY KEY,
    dataset_type TEXT NOT NULL,
    dimension_weights JSONB NOT NULL,
    quality_gate_pass_threshold DOUBLE PRECISION NOT NULL,
    quality_gate_warning_threshold DOUBLE PRECISION NOT NULL,
    severity_weights JSONB NOT NULL,
    criticality_weights JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS score_run (
    score_run_id TEXT PRIMARY KEY,
    validation_run_id TEXT NOT NULL REFERENCES validation_run(validation_run_id),
    scoring_policy_id TEXT NOT NULL REFERENCES scoring_policy(scoring_policy_id),
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(dataset_version_id),
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rule_score_history (
    score_run_id TEXT NOT NULL REFERENCES score_run(score_run_id),
    binding_id TEXT NOT NULL REFERENCES dataset_rule_binding(binding_id),
    dimension TEXT NOT NULL,
    rule_score DOUBLE PRECISION,
    measurement_status TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    base_rule_weight DOUBLE PRECISION NOT NULL,
    severity_weight DOUBLE PRECISION NOT NULL,
    criticality_weight DOUBLE PRECISION NOT NULL,
    effective_weight DOUBLE PRECISION NOT NULL,
    explanation_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (score_run_id, binding_id)
);

CREATE TABLE IF NOT EXISTS dimension_score_history (
    score_run_id TEXT NOT NULL REFERENCES score_run(score_run_id),
    dimension TEXT NOT NULL,
    dimension_score DOUBLE PRECISION,
    original_dimension_weight DOUBLE PRECISION NOT NULL,
    normalized_dimension_weight DOUBLE PRECISION NOT NULL,
    measurement_status TEXT NOT NULL,
    PRIMARY KEY (score_run_id, dimension)
);

CREATE TABLE IF NOT EXISTS dataset_score_history (
    score_run_id TEXT PRIMARY KEY REFERENCES score_run(score_run_id),
    dataset_dq_score DOUBLE PRECISION,
    quality_gate_status TEXT NOT NULL,
    measured_dimensions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    excluded_dimensions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    gate_failures JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS pipeline_log (
    log_id TEXT PRIMARY KEY,
    dataset_version_id TEXT REFERENCES dataset_version(dataset_version_id),
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
