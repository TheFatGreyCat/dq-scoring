-- Migration 023: user-confirmed column semantics, scoped to one immutable snapshot.
-- Advisory business context only; never touches privacy classification, manifests or assessments.

CREATE TABLE snapshot_semantic_state (
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
    PRIMARY KEY (tenant_id, snapshot_id),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES dataset_snapshots(tenant_id, snapshot_id) ON DELETE RESTRICT
);

CREATE TABLE snapshot_column_semantics (
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    column_name TEXT NOT NULL CHECK (char_length(column_name) BETWEEN 1 AND 1024),
    label TEXT NOT NULL CHECK (label IN (
        'UNKNOWN', 'IDENTIFIER', 'CATEGORY', 'FREE_TEXT', 'QUANTITY', 'MONEY',
        'DATE_TIME', 'EMAIL', 'PHONE', 'ADDRESS', 'PERSON_NAME', 'BOOLEAN'
    )),
    state TEXT NOT NULL DEFAULT 'CONFIRMED' CHECK (state = 'CONFIRMED'),
    revision BIGINT NOT NULL CHECK (revision >= 1),
    updated_by UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 500 AND reason ~ '\S'),
    PRIMARY KEY (tenant_id, snapshot_id, column_name),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES snapshot_semantic_state(tenant_id, snapshot_id) ON DELETE RESTRICT
);

CREATE TABLE snapshot_column_semantic_history (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    snapshot_id UUID NOT NULL,
    revision BIGINT NOT NULL CHECK (revision >= 1),
    column_name TEXT NOT NULL CHECK (char_length(column_name) BETWEEN 1 AND 1024),
    action TEXT NOT NULL CHECK (action IN ('CONFIRM', 'RESET')),
    label TEXT,
    previous_label TEXT,
    actor_user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 500 AND reason ~ '\S'),
    CHECK ((action = 'CONFIRM') = (label IS NOT NULL)),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES snapshot_semantic_state(tenant_id, snapshot_id) ON DELETE RESTRICT
);
CREATE INDEX idx_semantic_history_snapshot ON snapshot_column_semantic_history(tenant_id, snapshot_id, revision DESC);

CREATE TRIGGER no_semantic_history_update BEFORE UPDATE OR DELETE ON snapshot_column_semantic_history
    FOR EACH ROW EXECUTE FUNCTION reject_immutable_update();

-- Optimistic concurrency: the snapshot revision only ever advances by exactly one.
CREATE FUNCTION enforce_semantic_revision() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.revision <> 0 THEN
            RAISE EXCEPTION 'SEMANTIC_REVISION_INVALID' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' OR NEW.revision <> OLD.revision + 1
       OR (NEW.tenant_id, NEW.snapshot_id) IS DISTINCT FROM (OLD.tenant_id, OLD.snapshot_id) THEN
        RAISE EXCEPTION 'SEMANTIC_REVISION_INVALID' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER semantic_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON snapshot_semantic_state
    FOR EACH ROW EXECUTE FUNCTION enforce_semantic_revision();
REVOKE ALL ON FUNCTION enforce_semantic_revision() FROM PUBLIC;

-- Coherence the app role cannot bypass: state, projection and history must agree at commit.
-- The request user id is not a session setting here (app.current_user_id is cleared), so the actor is
-- authenticated by an ACTIVE write-role membership in the tenant instead.
CREATE FUNCTION enforce_semantic_history() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.revision IS DISTINCT FROM (SELECT revision FROM public.snapshot_semantic_state
                                      WHERE tenant_id = NEW.tenant_id AND snapshot_id = NEW.snapshot_id)
       OR NOT EXISTS (SELECT 1 FROM public.tenant_memberships m WHERE m.tenant_id = NEW.tenant_id
                      AND m.user_id = NEW.actor_user_id AND m.status = 'ACTIVE'
                      AND m.role IN ('DATA_ENGINEER', 'DATA_OWNER', 'DATA_STEWARD', 'WORKSPACE_ADMIN')) THEN
        RAISE EXCEPTION 'SEMANTIC_HISTORY_INVALID' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER semantic_history_guard BEFORE INSERT ON snapshot_column_semantic_history
    FOR EACH ROW EXECUTE FUNCTION enforce_semantic_history();

CREATE FUNCTION enforce_semantic_projection() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.revision IS DISTINCT FROM (SELECT revision FROM public.snapshot_semantic_state
                                      WHERE tenant_id = NEW.tenant_id AND snapshot_id = NEW.snapshot_id) THEN
        RAISE EXCEPTION 'SEMANTIC_PROJECTION_INVALID' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER semantic_projection_guard BEFORE INSERT OR UPDATE ON snapshot_column_semantics
    FOR EACH ROW EXECUTE FUNCTION enforce_semantic_projection();

CREATE FUNCTION check_semantic_commit() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE ok BOOLEAN;
BEGIN
    IF TG_TABLE_NAME = 'snapshot_semantic_state' THEN
        ok := EXISTS (SELECT 1 FROM public.snapshot_column_semantic_history h WHERE h.tenant_id = NEW.tenant_id
                      AND h.snapshot_id = NEW.snapshot_id AND h.revision = NEW.revision);
    ELSIF TG_OP = 'DELETE' THEN
        ok := EXISTS (SELECT 1 FROM public.snapshot_column_semantic_history h
                      JOIN public.snapshot_semantic_state s ON s.tenant_id = h.tenant_id AND s.snapshot_id = h.snapshot_id
                       AND s.revision = h.revision
                      WHERE h.tenant_id = OLD.tenant_id AND h.snapshot_id = OLD.snapshot_id
                        AND h.column_name = OLD.column_name AND h.action = 'RESET');
    ELSE
        ok := EXISTS (SELECT 1 FROM public.snapshot_column_semantic_history h WHERE h.tenant_id = NEW.tenant_id
                      AND h.snapshot_id = NEW.snapshot_id AND h.revision = NEW.revision AND h.column_name = NEW.column_name
                      AND h.action = 'CONFIRM' AND h.label = NEW.label AND h.actor_user_id = NEW.updated_by);
    END IF;
    IF NOT ok THEN
        RAISE EXCEPTION 'SEMANTIC_HISTORY_MISSING' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER semantic_state_history_required AFTER UPDATE ON snapshot_semantic_state
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_semantic_commit();
CREATE CONSTRAINT TRIGGER semantic_projection_history_required AFTER INSERT OR UPDATE OR DELETE ON snapshot_column_semantics
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_semantic_commit();
REVOKE ALL ON FUNCTION enforce_semantic_history(), enforce_semantic_projection(), check_semantic_commit() FROM PUBLIC;

ALTER TABLE snapshot_semantic_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshot_semantic_state FORCE ROW LEVEL SECURITY;
CREATE POLICY semantic_state_tenant ON snapshot_semantic_state FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE snapshot_column_semantics ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshot_column_semantics FORCE ROW LEVEL SECURITY;
CREATE POLICY column_semantics_tenant ON snapshot_column_semantics FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

ALTER TABLE snapshot_column_semantic_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshot_column_semantic_history FORCE ROW LEVEL SECURITY;
CREATE POLICY semantic_history_tenant ON snapshot_column_semantic_history FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::UUID);

GRANT SELECT ON snapshot_semantic_state TO dq_app_role;
GRANT INSERT (tenant_id, snapshot_id) ON snapshot_semantic_state TO dq_app_role;
GRANT UPDATE (revision) ON snapshot_semantic_state TO dq_app_role;
GRANT SELECT, DELETE ON snapshot_column_semantics TO dq_app_role;
GRANT INSERT (tenant_id, snapshot_id, column_name, label, revision, updated_by, reason) ON snapshot_column_semantics TO dq_app_role;
GRANT UPDATE (label, revision, updated_by, updated_at, reason) ON snapshot_column_semantics TO dq_app_role;
GRANT SELECT ON snapshot_column_semantic_history TO dq_app_role;
GRANT INSERT (tenant_id, snapshot_id, revision, column_name, action, label, previous_label, actor_user_id, reason)
    ON snapshot_column_semantic_history TO dq_app_role;
