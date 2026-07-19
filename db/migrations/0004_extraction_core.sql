-- Extraction core: tenant-scoped policies/runs/proposals/reviews and
-- immutable approved versions, plus shared calibrator artifacts
-- (M3-CONTRACT, ADR-0007, issue #101).
--
-- Tenancy rationale (ADR-0004 + ADR-0007):
-- * confidence_calibrators are shared evaluation artifacts (no org_id),
--   SELECT-only to fel_app; written only by the evaluation/release role.
-- * All other tables are tenant analysis records: every row carries org_id,
--   RLS keys off fel_claim_org_id(), and append-only / immutable tables
--   never receive UPDATE/DELETE grants where the data model forbids them.
--
-- Additive-only migration; follows 0001–0003 conventions. Requires prior
-- migrations including composite unique indexes from 0003
-- (workspaces(id, org_id), source_spans(id, document_version_id), …).

-- ---------------------------------------------------------------------------
-- Shared immutable calibrator artifacts (no org_id, SELECT-only fel_app)
-- ---------------------------------------------------------------------------

CREATE TABLE confidence_calibrators (
    id uuid PRIMARY KEY,
    output_family text NOT NULL,
    version text NOT NULL,
    dataset_id text NOT NULL,
    dataset_hash text NOT NULL CHECK (dataset_hash ~ '^sha256:[0-9a-f]{64}$'),
    algorithm text NOT NULL DEFAULT 'isotonic-v1'
        CHECK (algorithm = 'isotonic-v1'),
    breakpoints jsonb NOT NULL,
    sample_count integer NOT NULL CHECK (sample_count >= 1),
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (output_family, version, dataset_id, artifact_hash)
);

GRANT SELECT ON confidence_calibrators TO fel_app;

-- ---------------------------------------------------------------------------
-- Tenant-scoped extraction records (org_id + RLS)
-- ---------------------------------------------------------------------------

CREATE TABLE extraction_policies (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    version integer NOT NULL CHECK (version >= 1),
    record_threshold numeric(4, 3) NOT NULL DEFAULT 0.850
        CHECK (record_threshold BETWEEN 0 AND 1),
    field_threshold numeric(4, 3) NOT NULL DEFAULT 0.800
        CHECK (field_threshold BETWEEN 0 AND 1),
    max_calls integer NOT NULL DEFAULT 10
        CHECK (max_calls BETWEEN 1 AND 10),
    max_input_tokens integer NOT NULL DEFAULT 100000
        CHECK (max_input_tokens BETWEEN 1 AND 100000),
    max_output_tokens integer NOT NULL DEFAULT 20000
        CHECK (max_output_tokens BETWEEN 1 AND 20000),
    max_cost_usd numeric(12, 6) NOT NULL DEFAULT 2.0
        CHECK (max_cost_usd > 0 AND max_cost_usd <= 2.0),
    max_wall_seconds integer NOT NULL DEFAULT 600
        CHECK (max_wall_seconds BETWEEN 1 AND 600),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    supersedes_id uuid,
    UNIQUE (org_id, version),
    UNIQUE (id, org_id),
    FOREIGN KEY (org_id, created_by)
        REFERENCES memberships (org_id, user_id),
    FOREIGN KEY (supersedes_id, org_id)
        REFERENCES extraction_policies (id, org_id)
);
CREATE INDEX extraction_policies_org_idx
    ON extraction_policies (org_id, version DESC);

CREATE TABLE extraction_runs (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    workspace_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'running', 'waiting_review',
            'succeeded', 'failed', 'cancelled'
        )),
    modes text[] NOT NULL,
    as_of timestamptz NOT NULL,
    corpus_version_id uuid NOT NULL REFERENCES corpus_versions (id),
    ontology_version text NOT NULL,
    workflow_version text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    policy_id uuid NOT NULL,
    input_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
    input_hash text NOT NULL CHECK (input_hash ~ '^sha256:[0-9a-f]{64}$'),
    idempotency_key text NOT NULL CHECK (char_length(idempotency_key) >= 8),
    max_calls integer NOT NULL DEFAULT 10
        CHECK (max_calls BETWEEN 1 AND 10),
    max_input_tokens integer NOT NULL DEFAULT 100000
        CHECK (max_input_tokens BETWEEN 1 AND 100000),
    max_output_tokens integer NOT NULL DEFAULT 20000
        CHECK (max_output_tokens BETWEEN 1 AND 20000),
    max_cost_usd numeric(12, 6) NOT NULL DEFAULT 2.0
        CHECK (max_cost_usd > 0 AND max_cost_usd <= 2.0),
    max_wall_seconds integer NOT NULL DEFAULT 600
        CHECK (max_wall_seconds BETWEEN 1 AND 600),
    calls_used integer NOT NULL DEFAULT 0 CHECK (calls_used >= 0),
    input_tokens_used integer NOT NULL DEFAULT 0 CHECK (input_tokens_used >= 0),
    output_tokens_used integer NOT NULL DEFAULT 0 CHECK (output_tokens_used >= 0),
    cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    parent_run_id uuid,
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    error jsonb,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CHECK (
        cardinality(modes) >= 1
        AND modes <@ ARRAY['kpi', 'guidance', 'revenue_driver']::text[]
    ),
    CHECK (
        (status IN ('succeeded', 'failed', 'cancelled')
            AND finished_at IS NOT NULL)
        OR (status NOT IN ('succeeded', 'failed', 'cancelled')
            AND finished_at IS NULL)
    ),
    UNIQUE (id, org_id),
    UNIQUE (id, org_id, workspace_id),
    UNIQUE (org_id, workspace_id, idempotency_key),
    FOREIGN KEY (workspace_id, org_id)
        REFERENCES workspaces (id, org_id),
    FOREIGN KEY (org_id, created_by)
        REFERENCES memberships (org_id, user_id),
    FOREIGN KEY (policy_id, org_id)
        REFERENCES extraction_policies (id, org_id),
    FOREIGN KEY (parent_run_id, org_id)
        REFERENCES extraction_runs (id, org_id)
);
CREATE INDEX extraction_runs_org_workspace_idx
    ON extraction_runs (org_id, workspace_id, created_at);
CREATE INDEX extraction_runs_parent_idx
    ON extraction_runs (parent_run_id)
    WHERE parent_run_id IS NOT NULL;

CREATE TABLE extraction_run_steps (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL,
    step_name text NOT NULL,
    attempt integer NOT NULL CHECK (attempt >= 1),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled'
        )),
    input_hash text NOT NULL CHECK (input_hash ~ '^sha256:[0-9a-f]{64}$'),
    output_hash text CHECK (
        output_hash IS NULL OR output_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    workflow_version text NOT NULL,
    schema_version text NOT NULL,
    prompt_version text NOT NULL,
    provider_response_id text,
    input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    error jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE (run_id, step_name, attempt),
    UNIQUE (id, org_id),
    FOREIGN KEY (run_id, org_id)
        REFERENCES extraction_runs (id, org_id)
);
-- Successful step replay key: one success per content-addressed input.
CREATE UNIQUE INDEX extraction_run_steps_success_uniq
    ON extraction_run_steps (run_id, step_name, input_hash, workflow_version)
    WHERE status = 'succeeded';
CREATE INDEX extraction_run_steps_org_run_idx
    ON extraction_run_steps (org_id, run_id);

CREATE TABLE extraction_run_events (
    id bigint GENERATED ALWAYS AS IDENTITY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'run_queued', 'run_started', 'step_started', 'step_completed',
        'step_failed', 'budget_updated', 'proposals_persisted',
        'review_waiting', 'review_completed', 'run_succeeded',
        'run_failed', 'run_cancelled', 'heartbeat'
    )),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (org_id, run_id, id),
    FOREIGN KEY (run_id, org_id)
        REFERENCES extraction_runs (id, org_id)
);
CREATE INDEX extraction_run_events_org_run_idx
    ON extraction_run_events (org_id, run_id, id);

CREATE TABLE extraction_proposals (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    workspace_id uuid NOT NULL,
    run_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('kpi', 'guidance', 'revenue_driver')),
    metric_id text NOT NULL,
    payload jsonb NOT NULL,
    raw_payload_hash text NOT NULL
        CHECK (raw_payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    definition_hash text NOT NULL
        CHECK (definition_hash ~ '^sha256:[0-9a-f]{64}$'),
    comparability_key jsonb NOT NULL DEFAULT '{}'::jsonb,
    record_confidence numeric(4, 3) NOT NULL
        CHECK (record_confidence BETWEEN 0 AND 1),
    field_confidences jsonb NOT NULL DEFAULT '{}'::jsonb,
    validation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    state text NOT NULL DEFAULT 'proposed'
        CHECK (state IN (
            'proposed', 'needs_review', 'accepted', 'rejected', 'superseded'
        )),
    review_priority text NOT NULL DEFAULT 'normal'
        CHECK (review_priority IN ('normal', 'high')),
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id),
    UNIQUE (id, org_id, workspace_id),
    UNIQUE (id, org_id, run_id),
    FOREIGN KEY (run_id, org_id, workspace_id)
        REFERENCES extraction_runs (id, org_id, workspace_id),
    FOREIGN KEY (workspace_id, org_id)
        REFERENCES workspaces (id, org_id)
);
CREATE INDEX extraction_proposals_org_run_idx
    ON extraction_proposals (org_id, run_id);
CREATE INDEX extraction_proposals_org_workspace_state_idx
    ON extraction_proposals (org_id, workspace_id, state);

CREATE TABLE extraction_proposal_evidence (
    org_id uuid NOT NULL REFERENCES organizations (id),
    proposal_id uuid NOT NULL,
    source_span_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN (
        'supports', 'definition', 'conflicts', 'derivation_input'
    )),
    citation_status text NOT NULL CHECK (citation_status IN (
        'verified', 'partial', 'contradictory', 'invalid'
    )),
    ordinal integer NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
    PRIMARY KEY (proposal_id, source_span_id, role),
    FOREIGN KEY (proposal_id, org_id)
        REFERENCES extraction_proposals (id, org_id),
    FOREIGN KEY (source_span_id, document_version_id)
        REFERENCES source_spans (id, document_version_id)
);
CREATE INDEX extraction_proposal_evidence_org_idx
    ON extraction_proposal_evidence (org_id, proposal_id);

CREATE TABLE extraction_conflicts (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    workspace_id uuid NOT NULL,
    conflict_key text NOT NULL,
    reason_codes text[] NOT NULL DEFAULT '{}'::text[],
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'superseded')),
    resolved_by uuid,
    resolved_at timestamptz,
    resolution_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id),
    UNIQUE (org_id, workspace_id, conflict_key),
    FOREIGN KEY (workspace_id, org_id)
        REFERENCES workspaces (id, org_id),
    FOREIGN KEY (org_id, resolved_by)
        REFERENCES memberships (org_id, user_id),
    CHECK (
        (status = 'open' AND resolved_at IS NULL AND resolved_by IS NULL)
        OR (status <> 'open')
    )
);
CREATE INDEX extraction_conflicts_org_workspace_idx
    ON extraction_conflicts (org_id, workspace_id, status);

CREATE TABLE extraction_conflict_members (
    conflict_id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    org_id uuid NOT NULL REFERENCES organizations (id),
    PRIMARY KEY (conflict_id, proposal_id),
    FOREIGN KEY (conflict_id, org_id)
        REFERENCES extraction_conflicts (id, org_id),
    FOREIGN KEY (proposal_id, org_id)
        REFERENCES extraction_proposals (id, org_id)
);
CREATE INDEX extraction_conflict_members_org_idx
    ON extraction_conflict_members (org_id, conflict_id);

CREATE TABLE extraction_reviews (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    workspace_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN (
        'accept', 'edit', 'reject', 'merge', 'rerun'
    )),
    actor_user_id uuid NOT NULL,
    reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 2000),
    request_id text,
    idempotency_key text NOT NULL CHECK (char_length(idempotency_key) >= 8),
    expected_versions jsonb NOT NULL,
    input_ids uuid[] NOT NULL,
    patch jsonb,
    result_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id),
    UNIQUE (org_id, idempotency_key, action),
    FOREIGN KEY (workspace_id, org_id)
        REFERENCES workspaces (id, org_id),
    FOREIGN KEY (org_id, actor_user_id)
        REFERENCES memberships (org_id, user_id)
);
CREATE INDEX extraction_reviews_org_workspace_idx
    ON extraction_reviews (org_id, workspace_id, created_at);

CREATE TABLE approved_extraction_records (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    workspace_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('kpi', 'guidance', 'revenue_driver')),
    metric_id text NOT NULL,
    entity_id uuid NOT NULL,
    current_version_id uuid,
    version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id),
    UNIQUE (id, org_id, workspace_id),
    FOREIGN KEY (workspace_id, org_id)
        REFERENCES workspaces (id, org_id)
);
CREATE INDEX approved_extraction_records_org_workspace_idx
    ON approved_extraction_records (org_id, workspace_id, kind);

CREATE TABLE approved_extraction_versions (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    record_id uuid NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    parent_version_id uuid,
    origin_proposal_id uuid,
    payload jsonb NOT NULL,
    comparability_key jsonb NOT NULL DEFAULT '{}'::jsonb,
    evidence_manifest jsonb NOT NULL,
    evidence_manifest_hash text NOT NULL
        CHECK (evidence_manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    ontology_version text NOT NULL,
    normalizer_version text NOT NULL,
    validator_version text NOT NULL,
    approved_by uuid NOT NULL,
    approval_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (record_id, version),
    UNIQUE (id, org_id),
    UNIQUE (id, org_id, record_id),
    FOREIGN KEY (record_id, org_id)
        REFERENCES approved_extraction_records (id, org_id),
    FOREIGN KEY (parent_version_id, org_id, record_id)
        REFERENCES approved_extraction_versions (id, org_id, record_id),
    FOREIGN KEY (origin_proposal_id, org_id)
        REFERENCES extraction_proposals (id, org_id),
    FOREIGN KEY (org_id, approved_by)
        REFERENCES memberships (org_id, user_id)
);
CREATE INDEX approved_extraction_versions_org_record_idx
    ON approved_extraction_versions (org_id, record_id, version);

-- Head pointer FK after versions exist (additive cycle break).
ALTER TABLE approved_extraction_records
    ADD CONSTRAINT approved_extraction_records_current_version_fk
    FOREIGN KEY (current_version_id, org_id, id)
        REFERENCES approved_extraction_versions (id, org_id, record_id);

-- ---------------------------------------------------------------------------
-- Guards: legal transitions, append-only, immutability, open-run checks
-- ---------------------------------------------------------------------------

CREATE FUNCTION fel_guard_extraction_policy() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'extraction_policies are immutable';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'extraction_policies are immutable; insert a new version';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_policies_immutable
    BEFORE UPDATE OR DELETE ON extraction_policies
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_policy();

CREATE FUNCTION fel_guard_extraction_run() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    legal boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'extraction_runs cannot be deleted';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' THEN
            RAISE EXCEPTION 'new extraction runs must start queued';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'terminal extraction run cannot be mutated';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.org_id IS DISTINCT FROM OLD.org_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.entity_id IS DISTINCT FROM OLD.entity_id
       OR NEW.modes IS DISTINCT FROM OLD.modes
       OR NEW.as_of IS DISTINCT FROM OLD.as_of
       OR NEW.corpus_version_id IS DISTINCT FROM OLD.corpus_version_id
       OR NEW.ontology_version IS DISTINCT FROM OLD.ontology_version
       OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
       OR NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.model IS DISTINCT FROM OLD.model
       OR NEW.policy_id IS DISTINCT FROM OLD.policy_id
       OR NEW.input_manifest IS DISTINCT FROM OLD.input_manifest
       OR NEW.input_hash IS DISTINCT FROM OLD.input_hash
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.parent_run_id IS DISTINCT FROM OLD.parent_run_id
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'extraction run identity pins are immutable';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        legal := (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
            OR (OLD.status = 'running' AND NEW.status IN (
                'waiting_review', 'succeeded', 'failed', 'cancelled'
            ))
            OR (OLD.status = 'waiting_review' AND NEW.status IN (
                'succeeded', 'failed', 'cancelled'
            ));
        IF NOT legal THEN
            RAISE EXCEPTION 'illegal extraction run transition % -> %',
                OLD.status, NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_runs_guard
    BEFORE INSERT OR UPDATE OR DELETE ON extraction_runs
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_run();

CREATE FUNCTION fel_assert_extraction_run_open(
    child_run_id uuid, child_org_id uuid
) RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    run_status text;
BEGIN
    SELECT status INTO run_status
    FROM extraction_runs
    WHERE id = child_run_id AND org_id = child_org_id
    FOR SHARE;
    IF run_status IS NULL THEN
        RAISE EXCEPTION 'run child has no same-organization extraction run';
    END IF;
    IF run_status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'cannot append after extraction run is terminal';
    END IF;
END
$$;

CREATE FUNCTION fel_guard_extraction_run_child() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
    END IF;
    IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'extraction_run_steps' THEN
        -- Steps may advance status/output within an open run.
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.org_id IS DISTINCT FROM OLD.org_id
           OR NEW.run_id IS DISTINCT FROM OLD.run_id
           OR NEW.step_name IS DISTINCT FROM OLD.step_name
           OR NEW.attempt IS DISTINCT FROM OLD.attempt
           OR NEW.input_hash IS DISTINCT FROM OLD.input_hash
           OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
           OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
           OR NEW.prompt_version IS DISTINCT FROM OLD.prompt_version THEN
            RAISE EXCEPTION 'extraction_run_steps identity pins are immutable';
        END IF;
        -- A succeeded step is a stable replay key; forbid leaving 'succeeded'
        -- so the partial success-uniqueness index cannot be freed and reused.
        IF OLD.status = 'succeeded'
           AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'succeeded extraction_run_steps cannot change status';
        END IF;
        PERFORM fel_assert_extraction_run_open(NEW.run_id, NEW.org_id);
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
    END IF;
    PERFORM fel_assert_extraction_run_open(NEW.run_id, NEW.org_id);
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_run_steps_guard
    BEFORE INSERT OR UPDATE OR DELETE ON extraction_run_steps
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_run_child();
CREATE TRIGGER extraction_run_events_guard
    BEFORE INSERT OR UPDATE OR DELETE ON extraction_run_events
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_run_child();

CREATE FUNCTION fel_guard_extraction_proposal() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'extraction_proposals cannot be deleted';
    END IF;
    IF TG_OP = 'INSERT' THEN
        PERFORM fel_assert_extraction_run_open(NEW.run_id, NEW.org_id);
        RETURN NEW;
    END IF;
    -- Proposals freeze once their parent run reaches a terminal state; the
    -- review lifecycle (state/version) may only advance while the run is open.
    PERFORM fel_assert_extraction_run_open(NEW.run_id, NEW.org_id);
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.org_id IS DISTINCT FROM OLD.org_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.metric_id IS DISTINCT FROM OLD.metric_id
       OR NEW.payload IS DISTINCT FROM OLD.payload
       OR NEW.raw_payload_hash IS DISTINCT FROM OLD.raw_payload_hash
       OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash
       OR NEW.comparability_key IS DISTINCT FROM OLD.comparability_key
       OR NEW.record_confidence IS DISTINCT FROM OLD.record_confidence
       OR NEW.field_confidences IS DISTINCT FROM OLD.field_confidences
       OR NEW.validation_summary IS DISTINCT FROM OLD.validation_summary
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'extraction proposal payload/hashes/run are immutable';
    END IF;
    IF NEW.version < OLD.version THEN
        RAISE EXCEPTION 'extraction proposal version cannot decrease';
    END IF;
    IF NEW.version > OLD.version AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'extraction proposal version must advance by 1';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_proposals_guard
    BEFORE INSERT OR UPDATE OR DELETE ON extraction_proposals
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_proposal();

CREATE FUNCTION fel_guard_extraction_proposal_evidence() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    proposal_run uuid;
BEGIN
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'extraction_proposal_evidence is append-only';
    END IF;
    SELECT run_id INTO proposal_run
    FROM extraction_proposals
    WHERE id = NEW.proposal_id AND org_id = NEW.org_id;
    IF proposal_run IS NULL THEN
        RAISE EXCEPTION 'evidence has no same-organization proposal';
    END IF;
    PERFORM fel_assert_extraction_run_open(proposal_run, NEW.org_id);
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_proposal_evidence_guard
    BEFORE INSERT OR UPDATE OR DELETE ON extraction_proposal_evidence
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_proposal_evidence();

CREATE FUNCTION fel_guard_extraction_conflict() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'extraction_conflicts cannot be deleted';
    END IF;
    -- Only the resolution lifecycle (status/resolved_by/resolved_at/
    -- resolution_note) may change; identity and provenance are pinned.
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.org_id IS DISTINCT FROM OLD.org_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.conflict_key IS DISTINCT FROM OLD.conflict_key
       OR NEW.reason_codes IS DISTINCT FROM OLD.reason_codes
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'extraction conflict identity pins are immutable';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_conflicts_guard
    BEFORE UPDATE OR DELETE ON extraction_conflicts
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_conflict();

CREATE FUNCTION fel_reject_append_only_extraction() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

CREATE TRIGGER extraction_reviews_append_only
    BEFORE UPDATE OR DELETE ON extraction_reviews
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_extraction();

CREATE TRIGGER approved_extraction_versions_append_only
    BEFORE UPDATE OR DELETE ON approved_extraction_versions
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_extraction();

CREATE FUNCTION fel_guard_confidence_calibrator() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'confidence_calibrators are immutable';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER confidence_calibrators_immutable
    BEFORE UPDATE OR DELETE ON confidence_calibrators
    FOR EACH ROW EXECUTE FUNCTION fel_guard_confidence_calibrator();

-- ---------------------------------------------------------------------------
-- Grants + RLS
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT ON extraction_policies TO fel_app;
GRANT SELECT, INSERT ON extraction_runs TO fel_app;
GRANT UPDATE (
    status, calls_used, input_tokens_used, output_tokens_used, cost_usd,
    version, error, started_at, finished_at
) ON extraction_runs TO fel_app;
GRANT SELECT, INSERT, UPDATE ON extraction_run_steps TO fel_app;
GRANT SELECT, INSERT ON extraction_run_events TO fel_app;
GRANT SELECT, INSERT, UPDATE (
    state, review_priority, version
) ON extraction_proposals TO fel_app;
GRANT SELECT, INSERT ON extraction_proposal_evidence TO fel_app;
GRANT SELECT, INSERT, UPDATE (
    status, resolved_by, resolved_at, resolution_note
) ON extraction_conflicts TO fel_app;
GRANT SELECT, INSERT ON extraction_conflict_members TO fel_app;
GRANT SELECT, INSERT ON extraction_reviews TO fel_app;
GRANT SELECT, INSERT, UPDATE (
    current_version_id, version
) ON approved_extraction_records TO fel_app;
GRANT SELECT, INSERT ON approved_extraction_versions TO fel_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO fel_app;

ALTER TABLE extraction_policies ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_policies_isolation ON extraction_policies
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_runs_isolation ON extraction_runs
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_run_steps ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_run_steps_isolation ON extraction_run_steps
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_run_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_run_events_isolation ON extraction_run_events
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_proposals_isolation ON extraction_proposals
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_proposal_evidence ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_proposal_evidence_isolation
    ON extraction_proposal_evidence
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_conflicts ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_conflicts_isolation ON extraction_conflicts
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_conflict_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_conflict_members_isolation
    ON extraction_conflict_members
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE extraction_reviews ENABLE ROW LEVEL SECURITY;
CREATE POLICY extraction_reviews_isolation ON extraction_reviews
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE approved_extraction_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY approved_extraction_records_isolation
    ON approved_extraction_records
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE approved_extraction_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY approved_extraction_versions_isolation
    ON approved_extraction_versions
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());
