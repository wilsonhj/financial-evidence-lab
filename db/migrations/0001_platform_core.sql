-- Platform core: tenancy, workspaces, audit, usage metering, job queue.
-- RLS policies key off the per-request claims set by the API layer via
-- SET LOCAL request.jwt.claims (see apps/api/app/db.py). The service role
-- (workers/admin) bypasses RLS by design; API request paths must use a
-- non-privileged role.

CREATE TABLE organizations (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    org_id uuid NOT NULL REFERENCES organizations (id),
    user_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('owner', 'editor', 'reviewer', 'viewer')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE workspaces (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    name text NOT NULL,
    entity_id uuid NOT NULL,
    base_currency char(3) NOT NULL,
    fiscal_calendar text NOT NULL,
    as_of timestamptz NOT NULL,
    active_scenario_id uuid,
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workspaces_org_idx ON workspaces (org_id);

-- Append-only audit trail (no UPDATE/DELETE policies are ever added).
CREATE TABLE audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id uuid NOT NULL,
    actor_user_id uuid,
    request_id text,
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_org_idx ON audit_events (org_id, created_at);

CREATE TABLE usage_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    kind text NOT NULL,
    cost_usd numeric(12, 6) NOT NULL CHECK (cost_usd >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX usage_events_user_idx ON usage_events (org_id, user_id, created_at);

-- Durable job queue (contract: job-envelope/v1). Claimed with
-- FOR UPDATE SKIP LOCKED in a short transaction; processing happens outside
-- the claiming transaction; a reaper requeues stale heartbeats.
CREATE TABLE jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    queue text NOT NULL DEFAULT 'default',
    priority integer NOT NULL DEFAULT 5 CHECK (priority BETWEEN 0 AND 9),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
    idempotency_key text UNIQUE,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    org_id uuid,
    heartbeat_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error jsonb
);
CREATE INDEX jobs_claim_idx ON jobs (queue, priority, created_at) WHERE status = 'queued';

-- Idempotency-Key replay store for mutating API endpoints.
CREATE TABLE idempotency_keys (
    key text NOT NULL,
    org_id uuid NOT NULL,
    endpoint text NOT NULL,
    response_status integer NOT NULL,
    response_body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (key, org_id, endpoint)
);

-- Non-privileged application role used by API request paths. RLS applies to
-- it; the migration-applying superuser and worker service role bypass RLS.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fel_app') THEN
        CREATE ROLE fel_app NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO fel_app;
GRANT SELECT, INSERT, UPDATE ON organizations, memberships, workspaces TO fel_app;
GRANT SELECT, INSERT ON audit_events, usage_events TO fel_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys TO fel_app;
GRANT SELECT, INSERT ON jobs TO fel_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO fel_app;

-- Row-level security: org_id must match the per-request claims. Claims are
-- read from request.jwt.claims (Supabase-compatible); missing claims yield
-- NULL and therefore no rows. user_metadata is never consulted.
CREATE OR REPLACE FUNCTION fel_claim_org_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT (NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'org_id')::uuid
$$;

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON organizations
    USING (id = fel_claim_org_id())
    WITH CHECK (id = fel_claim_org_id());

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
CREATE POLICY membership_isolation ON memberships
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON workspaces
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_insert ON audit_events FOR INSERT
    WITH CHECK (org_id = fel_claim_org_id());
CREATE POLICY audit_read ON audit_events FOR SELECT
    USING (org_id = fel_claim_org_id());

ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY usage_isolation ON usage_events
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY idempotency_isolation ON idempotency_keys
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY jobs_tenant ON jobs
    USING (org_id IS NULL OR org_id = fel_claim_org_id())
    WITH CHECK (org_id IS NULL OR org_id = fel_claim_org_id());
