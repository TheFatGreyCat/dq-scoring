ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS rule_name TEXT;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS family TEXT;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS required_columns TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS backend_support TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS exclusions JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS parameters_schema JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS recommendation_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE rule_template ADD COLUMN IF NOT EXISTS description_for_recommendation TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'rule_template_lifecycle_status_check'
    ) THEN
        ALTER TABLE rule_template ADD CONSTRAINT rule_template_lifecycle_status_check CHECK (lifecycle_status IN ('draft', 'tested', 'active', 'deprecated', 'retired'));
    END IF;
END $$;