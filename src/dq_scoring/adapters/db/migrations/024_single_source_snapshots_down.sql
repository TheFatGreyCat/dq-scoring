-- Refuses (without touching data) once any v2 source descriptor exists; restores the exact 022 definitions otherwise.
SET LOCAL row_security=off;
LOCK TABLE snapshot_profile_jobs IN ACCESS EXCLUSIVE MODE;
LOCK TABLE dataset_snapshots IN SHARE ROW EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM dataset_snapshots WHERE source_descriptor ? 'descriptor_version') THEN
        RAISE EXCEPTION 'SINGLE_SOURCE_SNAPSHOTS_IN_USE';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_snapshot_profile_transition() RETURNS TRIGGER
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
END $$;;

CREATE OR REPLACE FUNCTION snapshot_profile_fingerprint(t UUID, s UUID, schema_doc JSONB, source_doc JSONB, version TEXT)
RETURNS TEXT LANGUAGE SQL IMMUTABLE STRICT SET search_path = pg_catalog, public AS $$
    SELECT encode(public.digest(jsonb_build_object(
        'tenant',t,'snapshot',s,'schema',schema_doc - 'privacy',
        'canonical',jsonb_build_object('bucket',source_doc->'canonical'->'bucket',
            'key',source_doc->'canonical'->'key','version',source_doc->'canonical'->'version_id',
            'sha256',source_doc->'canonical'->'content_sha256'),
        'normalization',source_doc->'normalization_version',
        'profiler',version)::text,'sha256'),'hex')
$$;;

DROP FUNCTION snapshot_source_is_profileable(JSONB);
DROP FUNCTION snapshot_v2_columns_valid(JSONB,JSONB);
