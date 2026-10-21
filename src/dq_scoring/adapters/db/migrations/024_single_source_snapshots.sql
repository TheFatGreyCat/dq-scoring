-- Descriptor v2: one immutable raw object + read-time normalization. Legacy (canonical) branch is the exact 022 expression.
CREATE FUNCTION snapshot_v2_columns_valid(cols JSONB, spec_version JSONB) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(bool_and(COALESCE(CASE WHEN jsonb_typeof(e.c)='object' THEN
            NOT EXISTS (SELECT 1 FROM jsonb_object_keys(e.c) k(key) WHERE k.key NOT IN
                ('index','original_name','name','type','nullable','structural_encoding','logical_types'))
            AND e.c->'index' = to_jsonb(e.i - 1)
            AND jsonb_typeof(e.c->'original_name')='string'
            AND jsonb_typeof(e.c->'name')='string' AND char_length(e.c->>'name')>0
            AND jsonb_typeof(e.c->'type')='string' AND char_length(e.c->>'type')>0
            AND jsonb_typeof(e.c->'nullable')='boolean'
            AND (NOT (e.c ? 'structural_encoding') OR e.c->'structural_encoding'='null'::jsonb
                 OR (e.c->'structural_encoding'='"JSON"'::jsonb AND spec_version='2'::jsonb))
            AND (NOT (e.c ? 'logical_types') OR (jsonb_typeof(e.c->'logical_types')='array'
                 AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(e.c->'logical_types') t(v) WHERE jsonb_typeof(t.v)<>'string')))
        ELSE FALSE END, FALSE)), FALSE)
        AND count(DISTINCT e.c->>'name') = count(*)
    FROM jsonb_array_elements(cols) WITH ORDINALITY AS e(c, i)
$$;

CREATE FUNCTION snapshot_source_is_profileable(source_doc JSONB) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE SET search_path = pg_catalog, public AS $$
    SELECT CASE
        WHEN NOT (source_doc ? 'descriptor_version') THEN source_doc->'canonical'->>'format' IS NOT DISTINCT FROM 'PARQUET'
        WHEN jsonb_typeof(source_doc) <> 'object' OR source_doc->'descriptor_version' <> '2'::jsonb THEN FALSE
        ELSE COALESCE(
            NOT EXISTS (SELECT 1 FROM jsonb_object_keys(source_doc) k(key) WHERE k.key NOT IN
                ('descriptor_version','storage_mode','bucket','key','version_id','content_sha256','size_bytes','format',
                 'normalization_version','normalization','source_id','source_binding_sha256'))
            AND source_doc->>'storage_mode' IN ('OWNED_RAW','EXTERNAL_VERSION')
            AND source_doc->>'format' IN ('CSV','JSONL','PARQUET')
            AND jsonb_typeof(source_doc->'bucket')='string' AND char_length(source_doc->>'bucket')>0
            AND jsonb_typeof(source_doc->'key')='string' AND char_length(source_doc->>'key')>0
            AND jsonb_typeof(source_doc->'version_id')='string' AND char_length(source_doc->>'version_id')>0
            AND source_doc->>'version_id' <> 'null'
            AND jsonb_typeof(source_doc->'content_sha256')='string' AND source_doc->>'content_sha256' ~ '^[0-9a-f]{64}$'
            AND jsonb_typeof(source_doc->'size_bytes')='number' AND source_doc->>'size_bytes' ~ '^[1-9][0-9]*$'
            AND source_doc->'normalization_version' IN ('1'::jsonb,'2'::jsonb)
            AND jsonb_typeof(source_doc->'normalization')='object'
            AND source_doc->'normalization'->'version' = source_doc->'normalization_version'
            AND source_doc->'normalization'->>'format' = source_doc->>'format'
            AND source_doc->'normalization'->>'encoding' = 'utf-8-sig'
            AND NOT EXISTS (SELECT 1 FROM jsonb_object_keys(source_doc->'normalization') k(key) WHERE k.key NOT IN
                ('version','format','delimiter','encoding','columns'))
            AND (NOT (source_doc->'normalization' ? 'delimiter')
                 OR source_doc->'normalization'->'delimiter' IN ('","'::jsonb,'";"'::jsonb,'"|"'::jsonb,'"\t"'::jsonb))
            AND CASE WHEN jsonb_typeof(source_doc->'normalization'->'columns')='array'
                     AND jsonb_array_length(source_doc->'normalization'->'columns') BETWEEN 1 AND 1000
                     THEN snapshot_v2_columns_valid(source_doc->'normalization'->'columns', source_doc->'normalization_version')
                     ELSE FALSE END
            AND CASE source_doc->>'storage_mode'
                WHEN 'EXTERNAL_VERSION' THEN source_doc->>'source_id'='shared'
                    AND jsonb_typeof(source_doc->'source_binding_sha256')='string'
                    AND source_doc->>'source_binding_sha256' ~ '^[0-9a-f]{64}$'
                ELSE NOT (source_doc ? 'source_id') AND NOT (source_doc ? 'source_binding_sha256')
            END, FALSE)
    END
$$;

CREATE OR REPLACE FUNCTION snapshot_profile_fingerprint(t UUID, s UUID, schema_doc JSONB, source_doc JSONB, version TEXT)
RETURNS TEXT LANGUAGE SQL IMMUTABLE STRICT SET search_path = pg_catalog, public AS $$
    SELECT encode(public.digest(CASE WHEN source_doc->'descriptor_version' = '2'::jsonb THEN
        jsonb_build_object(
            'tenant',t,'snapshot',s,'schema',schema_doc - 'privacy',
            'source',jsonb_build_object('descriptor_version',2,'source_id',source_doc->'source_id',
                'storage_mode',source_doc->'storage_mode','bucket',source_doc->'bucket','key',source_doc->'key',
                'version',source_doc->'version_id','sha256',source_doc->'content_sha256',
                'size',source_doc->'size_bytes','format',source_doc->'format',
                'binding',source_doc->'source_binding_sha256'),
            'normalization_version',source_doc->'normalization_version',
            'normalization',source_doc->'normalization',
            'profiler',version)::text
      ELSE
        jsonb_build_object('tenant',t,'snapshot',s,'schema',schema_doc - 'privacy',
        'canonical',jsonb_build_object('bucket',source_doc->'canonical'->'bucket',
            'key',source_doc->'canonical'->'key','version',source_doc->'canonical'->'version_id',
            'sha256',source_doc->'canonical'->'content_sha256'),
        'normalization',source_doc->'normalization_version',
        'profiler',version)::text
      END,'sha256'),'hex')
$$;

CREATE OR REPLACE FUNCTION enforce_snapshot_profile_transition() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE snap public.dataset_snapshots%ROWTYPE;
BEGIN
    IF TG_OP='INSERT' THEN
        SELECT * INTO snap FROM public.dataset_snapshots WHERE tenant_id=NEW.tenant_id AND snapshot_id=NEW.snapshot_id;
        IF NOT FOUND OR snap.source_kind<>'OBJECT_FILE' OR NOT public.snapshot_source_is_profileable(snap.source_descriptor)
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
