-- Durable statistical evidence, separate from immutable import manifests.
CREATE FUNCTION snapshot_profile_fingerprint(t UUID, s UUID, schema_doc JSONB, source_doc JSONB, version TEXT)
RETURNS TEXT LANGUAGE SQL IMMUTABLE STRICT SET search_path = pg_catalog, public AS $$
    SELECT encode(public.digest(jsonb_build_object(
        'tenant',t,'snapshot',s,'schema',schema_doc - 'privacy',
        'canonical',jsonb_build_object('bucket',source_doc->'canonical'->'bucket',
            'key',source_doc->'canonical'->'key','version',source_doc->'canonical'->'version_id',
            'sha256',source_doc->'canonical'->'content_sha256'),
        'normalization',source_doc->'normalization_version',
        'profiler',version)::text,'sha256'),'hex')
$$;

CREATE TABLE snapshot_profile_jobs (
    profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    snapshot_id UUID NOT NULL,
    fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    profiler_version TEXT NOT NULL CHECK (char_length(profiler_version) BETWEEN 1 AND 64),
    requested_by UUID REFERENCES users(user_id),
    state TEXT NOT NULL DEFAULT 'QUEUED' CHECK (state IN ('QUEUED','RUNNING','COMPLETE','FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    lease_owner TEXT CHECK (char_length(lease_owner) BETWEEN 1 AND 200),
    lease_generation BIGINT NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error_code TEXT CHECK (error_code IN ('PROFILE_FAILED','OBJECT_CHANGED','STORAGE_UNAVAILABLE',
        'SNAPSHOT_REIMPORT_REQUIRED','PROFILE_SCHEMA_MISMATCH','PROFILE_ROW_COUNT_MISMATCH','PROFILE_RESULT_INVALID')),
    result JSONB CHECK (jsonb_typeof(result)='object' AND octet_length(result::text)<=2097152),
    UNIQUE (tenant_id, snapshot_id, fingerprint),
    UNIQUE (tenant_id, snapshot_id, profile_id),
    FOREIGN KEY (tenant_id,snapshot_id) REFERENCES dataset_snapshots(tenant_id,snapshot_id),
    CHECK ((state='COMPLETE') = (result IS NOT NULL)),
    CHECK ((state='FAILED') = (error_code IS NOT NULL)),
    CHECK (state <> 'RUNNING' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK (state NOT IN ('COMPLETE','FAILED') OR finished_at IS NOT NULL)
);
CREATE INDEX snapshot_profiles_claim ON snapshot_profile_jobs(created_at,profile_id)
    WHERE state IN ('QUEUED','RUNNING');

CREATE FUNCTION enforce_snapshot_profile_transition() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE snap public.dataset_snapshots%ROWTYPE;
BEGIN
    IF TG_OP='INSERT' THEN
        SELECT * INTO snap FROM public.dataset_snapshots WHERE tenant_id=NEW.tenant_id AND snapshot_id=NEW.snapshot_id;
        IF NOT FOUND OR snap.source_kind<>'OBJECT_FILE' OR snap.source_descriptor->'canonical'->>'format' IS DISTINCT FROM 'PARQUET'
          OR NEW.fingerprint IS DISTINCT FROM public.snapshot_profile_fingerprint(NEW.tenant_id,NEW.snapshot_id,snap.schema_definition,snap.source_descriptor,NEW.profiler_version)
          OR NEW.state<>'QUEUED' OR NEW.result IS NOT NULL OR NEW.lease_generation<>0 OR NEW.attempt_count<>0
          OR NEW.lease_owner IS NOT NULL OR NEW.lease_expires_at IS NOT NULL THEN
            RAISE EXCEPTION 'PROFILE_SUBMISSION_INVALID' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state='COMPLETE' OR (NEW.profile_id,NEW.tenant_id,NEW.snapshot_id,NEW.fingerprint,NEW.profiler_version,NEW.created_at)
       IS DISTINCT FROM (OLD.profile_id,OLD.tenant_id,OLD.snapshot_id,OLD.fingerprint,OLD.profiler_version,OLD.created_at) THEN
        RAISE EXCEPTION 'PROFILE_IMMUTABLE' USING ERRCODE='23514';
    END IF;
    IF OLD.state='FAILED' AND NEW.state='QUEUED' THEN
        NEW.error_code=NULL; NEW.finished_at=NULL; NEW.started_at=NULL;
        NEW.heartbeat_at=NULL; NEW.lease_owner=NULL; NEW.lease_expires_at=NULL;
        RETURN NEW;
    END IF;
    IF NEW.state='RUNNING' AND (OLD.state='QUEUED' OR (OLD.state='RUNNING' AND OLD.lease_expires_at<clock_timestamp())) THEN
        IF NOT pg_has_role(current_user,'dq_dispatcher_role','MEMBER') AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) THEN
            RAISE EXCEPTION 'PROFILE_CLAIM_FORBIDDEN' USING ERRCODE='42501';
        END IF;
        IF NEW.lease_generation<>OLD.lease_generation+1 OR NEW.attempt_count<>OLD.attempt_count+1 THEN
            RAISE EXCEPTION 'PROFILE_CLAIM_INVALID' USING ERRCODE='23514';
        END IF;
    ELSIF OLD.state='RUNNING' AND OLD.lease_expires_at>=clock_timestamp()
      AND NEW.lease_generation=OLD.lease_generation AND NEW.lease_owner=OLD.lease_owner
      AND NEW.attempt_count=OLD.attempt_count AND NEW.state IN ('RUNNING','COMPLETE','FAILED') THEN
        IF NOT pg_has_role(current_user,'dq_worker_role','MEMBER') AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) THEN
            RAISE EXCEPTION 'PROFILE_PUBLICATION_FORBIDDEN' USING ERRCODE='42501';
        END IF;
        IF NEW.state='COMPLETE' AND (NEW.result->>'mode' IS DISTINCT FROM 'FULL'
          OR NEW.result->>'profile_id' IS DISTINCT FROM NEW.profile_id::text
          OR NEW.result->>'fingerprint' IS DISTINCT FROM NEW.fingerprint
          OR NEW.result->>'profiler_version' IS DISTINCT FROM NEW.profiler_version
          OR NEW.result->>'scanned_rows' IS DISTINCT FROM NEW.result->>'total_rows') THEN
            RAISE EXCEPTION 'PROFILE_RESULT_INVALID' USING ERRCODE='23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'PROFILE_TRANSITION_INVALID' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER snapshot_profile_transition BEFORE INSERT OR UPDATE ON snapshot_profile_jobs
    FOR EACH ROW EXECUTE FUNCTION enforce_snapshot_profile_transition();

ALTER TABLE snapshot_profile_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshot_profile_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY snapshot_profiles_tenant ON snapshot_profile_jobs FOR ALL
    USING (tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::UUID)
    WITH CHECK (tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::UUID);
CREATE POLICY snapshot_profiles_dispatch_read ON snapshot_profile_jobs FOR SELECT TO dq_dispatcher_role
    USING (state IN ('QUEUED','RUNNING'));
CREATE POLICY snapshot_profiles_dispatch_claim ON snapshot_profile_jobs FOR UPDATE TO dq_dispatcher_role
    USING (state='QUEUED' OR (state='RUNNING' AND lease_expires_at<clock_timestamp()))
    WITH CHECK (state='RUNNING');
GRANT SELECT ON snapshot_profile_jobs TO dq_app_role,dq_worker_role,dq_dispatcher_role;
GRANT INSERT (tenant_id,snapshot_id,fingerprint,profiler_version,requested_by) ON snapshot_profile_jobs TO dq_app_role;
GRANT UPDATE (state) ON snapshot_profile_jobs TO dq_app_role;
GRANT UPDATE (state,started_at,finished_at,heartbeat_at,lease_owner,lease_generation,lease_expires_at,attempt_count,error_code,result)
    ON snapshot_profile_jobs TO dq_worker_role;
GRANT UPDATE (state,started_at,heartbeat_at,lease_owner,lease_generation,lease_expires_at,attempt_count)
    ON snapshot_profile_jobs TO dq_dispatcher_role;
REVOKE ALL ON FUNCTION enforce_snapshot_profile_transition() FROM PUBLIC;

-- Enqueue only; no object access or Spark work in migrations. Fail rather than silently skip FORCE RLS rows.
SET LOCAL row_security=off;
INSERT INTO snapshot_profile_jobs(tenant_id,snapshot_id,fingerprint,profiler_version)
SELECT tenant_id,snapshot_id,snapshot_profile_fingerprint(tenant_id,snapshot_id,schema_definition,source_descriptor,'full-v1'),'full-v1'
FROM dataset_snapshots WHERE source_kind='OBJECT_FILE' AND source_descriptor->'canonical'->>'format'='PARQUET';
