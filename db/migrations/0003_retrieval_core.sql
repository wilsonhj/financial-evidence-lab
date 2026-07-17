-- Retrieval core: immutable shared index artifacts and tenant-scoped
-- query/trace/claim records (M2-CONTRACT, ADR-0006, issue #100).
--
-- Tenancy rationale (ADR-0004 + ADR-0006):
-- * retrieval_index_versions / retrieval_items / retrieval_embeddings are
--   public-corpus-derived, carry no org_id, and are SELECT-only to fel_app.
--   Workers (service role) alone build and publish indexes.
-- * queries, retrieval_runs, retrieval_events, retrieval_candidates,
--   retrieval_feedback, claims, and citations are tenant analysis records:
--   every row carries org_id, RLS keys off fel_claim_org_id(), and
--   append-only tables never receive UPDATE/DELETE grants.
--
-- Additive-only migration; follows 0001_platform_core.sql /
-- 0002_corpus_core.sql conventions. Leaves room for M3
-- 0004_extraction_core.sql (issue #101) — do not invent a second 0003_*.
--
-- Requires pgvector >= 0.8.2 (halfvec + HNSW). Local/CI smoke must use a
-- pgvector-enabled Postgres image (e.g. pgvector/pgvector:pg17).

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
DECLARE
    installed_version text;
BEGIN
    SELECT extversion INTO installed_version
    FROM pg_extension
    WHERE extname = 'vector';

    IF installed_version IS NULL OR
       (split_part(installed_version, '.', 1)::integer,
        split_part(installed_version, '.', 2)::integer,
        split_part(installed_version, '.', 3)::integer) < (0, 8, 2) THEN
        RAISE EXCEPTION 'pgvector >= 0.8.2 is required; installed version is %',
            COALESCE(installed_version, '<missing>');
    END IF;
END
$$;

-- Supporting unique indexes so retrieval_items can enforce span/section
-- version agreement via composite foreign keys (additive; 0002 PKs unchanged).
CREATE UNIQUE INDEX workspaces_id_org_uniq
    ON workspaces (id, org_id);
CREATE UNIQUE INDEX documents_id_entity_uniq
    ON documents (id, entity_id);
CREATE UNIQUE INDEX document_versions_id_document_uniq
    ON document_versions (id, document_id);
CREATE UNIQUE INDEX source_spans_id_version_uniq
    ON source_spans (id, document_version_id);
CREATE UNIQUE INDEX source_spans_id_version_section_uniq
    ON source_spans (id, document_version_id, section_id);
CREATE UNIQUE INDEX sections_id_version_uniq
    ON sections (id, document_version_id);
CREATE UNIQUE INDEX tables_meta_id_version_section_uniq
    ON tables_meta (id, document_version_id, section_id);
CREATE UNIQUE INDEX financial_facts_id_provenance_uniq
    ON financial_facts (
        id, entity_id, document_version_id, source_span_id
    );

-- ---------------------------------------------------------------------------
-- Shared immutable retrieval artifacts (no org_id, SELECT-only fel_app)
-- ---------------------------------------------------------------------------

-- Deterministic index version: UUIDv5 of
-- (corpus_version_id, config_hash, provider, model, dimensions, distance).
-- Identical pinned inputs resume/reuse the row; any change mints a new id.
CREATE TABLE retrieval_index_versions (
    id uuid PRIMARY KEY,
    corpus_version_id uuid NOT NULL REFERENCES corpus_versions (id),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'building', 'ready', 'failed', 'superseded')),
    chunker_version text NOT NULL,
    chunker_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_hash text NOT NULL CHECK (config_hash ~ '^sha256:[0-9a-f]{64}$'),
    embedding_provider text NOT NULL,
    embedding_model text NOT NULL,
    dimensions integer NOT NULL DEFAULT 512 CHECK (dimensions = 512),
    distance text NOT NULL DEFAULT 'cosine' CHECK (distance = 'cosine'),
    -- Exactly one ready active default; pins may target any ready/superseded
    -- published version (is_active false).
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (NOT is_active OR status = 'ready'),
    CHECK (
        (status IN ('ready', 'superseded') AND published_at IS NOT NULL)
        OR (status IN ('draft', 'building', 'failed') AND published_at IS NULL)
    ),
    UNIQUE (
        corpus_version_id,
        config_hash,
        embedding_provider,
        embedding_model,
        dimensions,
        distance
    ),
    UNIQUE (id, corpus_version_id),
    UNIQUE (id, embedding_provider, embedding_model, dimensions)
);
CREATE UNIQUE INDEX retrieval_index_versions_single_active
    ON retrieval_index_versions ((true))
    WHERE is_active;
CREATE INDEX retrieval_index_versions_corpus_idx
    ON retrieval_index_versions (corpus_version_id, status);

-- Normalized passage / table-row / fact items. id is UUIDv5 of
-- (index_version_id, kind, source_anchor, content_sha256).
CREATE TABLE retrieval_items (
    id uuid PRIMARY KEY,
    index_version_id uuid NOT NULL REFERENCES retrieval_index_versions (id),
    kind text NOT NULL CHECK (kind IN ('passage', 'table_row', 'fact')),
    entity_id uuid NOT NULL,
    document_id uuid NOT NULL REFERENCES documents (id),
    document_version_id uuid NOT NULL REFERENCES document_versions (id),
    section_id uuid NOT NULL REFERENCES sections (id),
    source_span_id uuid NOT NULL REFERENCES source_spans (id),
    financial_fact_id uuid REFERENCES financial_facts (id),
    table_id uuid REFERENCES tables_meta (id),
    table_row_index integer CHECK (table_row_index IS NULL OR table_row_index >= 0),
    content text NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    heading_path text[] NOT NULL DEFAULT '{}'::text[],
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL,
    token_count integer NOT NULL CHECK (token_count >= 0),
    -- Denormalized filter fields for lane B-trees (form/period).
    form text,
    period text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_char >= start_char),
    -- Exactly one kind-specific anchor.
    CHECK (
        (kind = 'passage'
            AND financial_fact_id IS NULL
            AND table_id IS NULL
            AND table_row_index IS NULL)
        OR (kind = 'fact'
            AND financial_fact_id IS NOT NULL
            AND table_id IS NULL
            AND table_row_index IS NULL)
        OR (kind = 'table_row'
            AND financial_fact_id IS NULL
            AND table_id IS NOT NULL
            AND table_row_index IS NOT NULL)
    ),
    -- Stable source-anchor identity for deterministic uniqueness.
    source_anchor text GENERATED ALWAYS AS (
        CASE kind
            WHEN 'passage' THEN 'span:' || source_span_id::text
            WHEN 'fact' THEN 'fact:' || financial_fact_id::text
            WHEN 'table_row' THEN
                'table:' || table_id::text || ':' || table_row_index::text
        END
    ) STORED,
    -- Span/document/section must agree on the selected document version.
    FOREIGN KEY (source_span_id, document_version_id)
        REFERENCES source_spans (id, document_version_id),
    FOREIGN KEY (source_span_id, document_version_id, section_id)
        REFERENCES source_spans (id, document_version_id, section_id),
    FOREIGN KEY (section_id, document_version_id)
        REFERENCES sections (id, document_version_id),
    FOREIGN KEY (document_version_id, document_id)
        REFERENCES document_versions (id, document_id),
    FOREIGN KEY (document_id, entity_id)
        REFERENCES documents (id, entity_id),
    FOREIGN KEY (
        financial_fact_id, entity_id, document_version_id, source_span_id
    ) REFERENCES financial_facts (
        id, entity_id, document_version_id, source_span_id
    ),
    FOREIGN KEY (table_id, document_version_id, section_id)
        REFERENCES tables_meta (id, document_version_id, section_id)
);

CREATE UNIQUE INDEX retrieval_items_anchor_uniq
    ON retrieval_items (index_version_id, kind, source_anchor, content_sha256);
CREATE UNIQUE INDEX retrieval_items_id_index_hash_uniq
    ON retrieval_items (id, index_version_id, content_sha256);
CREATE UNIQUE INDEX retrieval_items_id_span_uniq
    ON retrieval_items (id, source_span_id);
CREATE INDEX retrieval_items_index_entity_idx
    ON retrieval_items (index_version_id, entity_id);
CREATE INDEX retrieval_items_index_document_idx
    ON retrieval_items (index_version_id, document_id);
CREATE INDEX retrieval_items_index_form_idx
    ON retrieval_items (index_version_id, form)
    WHERE form IS NOT NULL;
CREATE INDEX retrieval_items_index_period_idx
    ON retrieval_items (index_version_id, period)
    WHERE period IS NOT NULL;
CREATE INDEX retrieval_items_search_vector_gin
    ON retrieval_items USING gin (search_vector);

-- Dense embeddings: halfvec(512), cosine HNSW (m=16, ef_construction=64).
CREATE TABLE retrieval_embeddings (
    retrieval_item_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    dimensions integer NOT NULL DEFAULT 512 CHECK (dimensions = 512),
    embedding halfvec(512) NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (retrieval_item_id, provider, model, dimensions),
    FOREIGN KEY (retrieval_item_id, index_version_id, content_sha256)
        REFERENCES retrieval_items (id, index_version_id, content_sha256),
    FOREIGN KEY (index_version_id, provider, model, dimensions)
        REFERENCES retrieval_index_versions (
            id, embedding_provider, embedding_model, dimensions
        )
);
CREATE INDEX retrieval_embeddings_index_idx
    ON retrieval_embeddings (index_version_id);
CREATE INDEX retrieval_embeddings_hnsw_cosine_idx
    ON retrieval_embeddings
    USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

GRANT SELECT ON retrieval_index_versions, retrieval_items, retrieval_embeddings
    TO fel_app;

-- ---------------------------------------------------------------------------
-- Tenant-scoped analysis records (org_id + RLS)
-- ---------------------------------------------------------------------------

-- Immutable query version; plan/index pins captured at creation.
CREATE TABLE queries (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    workspace_id uuid NOT NULL,
    created_by uuid NOT NULL,
    question text NOT NULL CHECK (char_length(question) BETWEEN 1 AND 4000),
    effective_as_of timestamptz NOT NULL,
    corpus_version_id uuid NOT NULL REFERENCES corpus_versions (id),
    index_version_id uuid NOT NULL,
    plan jsonb NOT NULL,
    planner_version text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    parent_query_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id),
    FOREIGN KEY (workspace_id, org_id)
        REFERENCES workspaces (id, org_id),
    FOREIGN KEY (org_id, created_by)
        REFERENCES memberships (org_id, user_id),
    FOREIGN KEY (index_version_id, corpus_version_id)
        REFERENCES retrieval_index_versions (id, corpus_version_id),
    FOREIGN KEY (parent_query_id, org_id)
        REFERENCES queries (id, org_id)
);
CREATE INDEX queries_org_workspace_idx ON queries (org_id, workspace_id, created_at);
CREATE INDEX queries_parent_idx ON queries (parent_query_id)
    WHERE parent_query_id IS NOT NULL;

-- Retrieval run status machine (ADR-0006). Stored-trace replay does not
-- insert a row; unchanged rerun creates a child with parent_run_id.
CREATE TABLE retrieval_runs (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    query_id uuid NOT NULL,
    parent_run_id uuid,
    mode text NOT NULL CHECK (mode IN ('execute', 'rerun')),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'planning', 'retrieving', 'fusing', 'generating',
            'verifying', 'succeeded', 'abstained', 'failed', 'cancelled'
        )),
    config_hash text NOT NULL CHECK (config_hash ~ '^sha256:[0-9a-f]{64}$'),
    embedding_provider text NOT NULL,
    embedding_model text NOT NULL,
    generation_provider text,
    generation_model text,
    planner_version text NOT NULL,
    budget_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    timings_ms jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error jsonb,
    CHECK ((mode = 'execute') = (parent_run_id IS NULL)),
    CHECK (
        (status IN ('succeeded', 'abstained', 'failed', 'cancelled')
            AND finished_at IS NOT NULL)
        OR (status NOT IN ('succeeded', 'abstained', 'failed', 'cancelled')
            AND finished_at IS NULL)
    ),
    UNIQUE (id, org_id),
    UNIQUE (id, org_id, query_id),
    FOREIGN KEY (query_id, org_id)
        REFERENCES queries (id, org_id),
    FOREIGN KEY (parent_run_id, org_id, query_id)
        REFERENCES retrieval_runs (id, org_id, query_id)
);
CREATE INDEX retrieval_runs_org_query_idx
    ON retrieval_runs (org_id, query_id, started_at);
CREATE INDEX retrieval_runs_parent_idx
    ON retrieval_runs (parent_run_id)
    WHERE parent_run_id IS NOT NULL;

-- Append-only ordered events; SSE event id is decimal seq.
CREATE TABLE retrieval_events (
    run_id uuid NOT NULL,
    org_id uuid NOT NULL REFERENCES organizations (id),
    seq bigint NOT NULL CHECK (seq >= 1),
    event_type text NOT NULL CHECK (event_type IN (
        'run_started', 'plan_ready', 'lane_started', 'candidate_batch',
        'lane_completed', 'fusion_completed', 'rerank_completed',
        'context_selected', 'claim_generated', 'citation_verified',
        'run_abstained', 'run_completed', 'run_failed', 'run_cancelled',
        'heartbeat'
    )),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id, org_id)
        REFERENCES retrieval_runs (id, org_id)
);
CREATE INDEX retrieval_events_org_idx ON retrieval_events (org_id, created_at);

-- Per-lane candidate contributions retained for Observatory replay.
CREATE TABLE retrieval_candidates (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL,
    retrieval_item_id uuid NOT NULL REFERENCES retrieval_items (id),
    lane text NOT NULL CHECK (lane IN ('dense', 'lexical', 'facts', 'tables')),
    variant_index integer NOT NULL CHECK (variant_index BETWEEN 0 AND 3),
    lane_rank integer NOT NULL CHECK (lane_rank >= 1),
    raw_score text NOT NULL
        CHECK (raw_score ~ '^-?[0-9]+(\.[0-9]+)?$'),
    normalized_score text CHECK (
        normalized_score IS NULL OR (
            normalized_score ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND normalized_score::numeric BETWEEN 0 AND 1
        )
    ),
    rrf_contribution text NOT NULL CHECK (
        rrf_contribution ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND rrf_contribution::numeric >= 0
    ),
    fused_score text NOT NULL CHECK (
        fused_score ~ '^-?[0-9]+(\.[0-9]+)?$'
        AND fused_score::numeric >= 0
    ),
    rerank_score text CHECK (
        rerank_score IS NULL
        OR rerank_score ~ '^-?[0-9]+(\.[0-9]+)?$'
    ),
    fused_rank integer CHECK (fused_rank IS NULL OR fused_rank >= 1),
    rerank_rank integer CHECK (rerank_rank IS NULL OR rerank_rank >= 1),
    accepted boolean NOT NULL,
    rejection_code text,
    decision_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    timing_ms integer NOT NULL CHECK (timing_ms >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, lane, variant_index, retrieval_item_id),
    FOREIGN KEY (run_id, org_id)
        REFERENCES retrieval_runs (id, org_id)
);
CREATE INDEX retrieval_candidates_org_run_idx
    ON retrieval_candidates (org_id, run_id);

CREATE TABLE retrieval_feedback (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL,
    retrieval_item_id uuid NOT NULL REFERENCES retrieval_items (id),
    label text NOT NULL CHECK (label IN (
        'relevant', 'irrelevant', 'duplicate', 'temporally_invalid'
    )),
    actor_user_id uuid NOT NULL,
    supersedes_feedback_id uuid,
    reason text CHECK (reason IS NULL OR char_length(reason) <= 2000),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (supersedes_feedback_id IS NULL OR supersedes_feedback_id <> id),
    UNIQUE (id, org_id, run_id),
    FOREIGN KEY (run_id, org_id)
        REFERENCES retrieval_runs (id, org_id),
    FOREIGN KEY (org_id, actor_user_id)
        REFERENCES memberships (org_id, user_id),
    FOREIGN KEY (supersedes_feedback_id, org_id, run_id)
        REFERENCES retrieval_feedback (id, org_id, run_id)
);
CREATE INDEX retrieval_feedback_org_run_idx
    ON retrieval_feedback (org_id, run_id);

-- Retrieval-produced claims (distinct from the frozen claim/v1 JSON shape
-- used elsewhere; DB rows carry org/run provenance for Observatory).
CREATE TABLE claims (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL,
    ord integer NOT NULL CHECK (ord >= 0),
    text text NOT NULL,
    status text NOT NULL CHECK (status IN (
        'supported', 'partially_supported', 'contradicted',
        'derived', 'unsupported'
    )),
    confidence text CHECK (
        confidence IS NULL OR (
            confidence ~ '^-?[0-9]+(\.[0-9]+)?$'
            AND confidence::numeric BETWEEN 0 AND 1
        )
    ),
    calculation_lineage jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, ord),
    UNIQUE (id, org_id, run_id),
    FOREIGN KEY (run_id, org_id)
        REFERENCES retrieval_runs (id, org_id)
);
CREATE INDEX claims_org_run_idx ON claims (org_id, run_id);

CREATE TABLE citations (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL,
    claim_id uuid NOT NULL,
    retrieval_item_id uuid NOT NULL,
    source_span_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN (
        'entailed', 'partial', 'contradictory', 'irrelevant'
    )),
    verifier text,
    model text,
    version text,
    numeric_checks jsonb NOT NULL DEFAULT '{}'::jsonb,
    rationale text,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (claim_id, org_id, run_id)
        REFERENCES claims (id, org_id, run_id),
    FOREIGN KEY (retrieval_item_id, source_span_id)
        REFERENCES retrieval_items (id, source_span_id),
    FOREIGN KEY (run_id, org_id)
        REFERENCES retrieval_runs (id, org_id)
);
CREATE INDEX citations_org_claim_idx ON citations (org_id, claim_id);

-- Cross-table invariants that cannot be represented by foreign keys alone.
CREATE FUNCTION fel_guard_retrieval_index_version() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'retrieval index versions are immutable';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' OR NEW.is_active OR NEW.published_at IS NOT NULL THEN
            RAISE EXCEPTION 'retrieval index versions must start as unpublished drafts';
        END IF;
        RETURN NEW;
    END IF;

    IF ROW(NEW.id, NEW.corpus_version_id, NEW.chunker_version,
           NEW.chunker_config, NEW.config_hash, NEW.embedding_provider,
           NEW.embedding_model, NEW.dimensions, NEW.distance, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.corpus_version_id, OLD.chunker_version,
           OLD.chunker_config, OLD.config_hash, OLD.embedding_provider,
           OLD.embedding_model, OLD.dimensions, OLD.distance, OLD.created_at) THEN
        RAISE EXCEPTION 'retrieval index identity and pins are immutable';
    END IF;

    IF OLD.status IN ('failed', 'superseded')
       OR (OLD.status = 'ready' AND NEW.status <> 'superseded') THEN
        RAISE EXCEPTION 'terminal retrieval index version is immutable';
    END IF;

    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'draft' AND NEW.status = 'building')
        OR (OLD.status = 'building' AND NEW.status IN ('ready', 'failed'))
        OR (OLD.status = 'ready' AND NEW.status = 'superseded')
    ) THEN
        RAISE EXCEPTION 'illegal retrieval index transition: % -> %',
            OLD.status, NEW.status;
    END IF;

    IF NEW.status = OLD.status AND (
        NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.is_active IS DISTINCT FROM OLD.is_active
    ) THEN
        RAISE EXCEPTION 'publication fields may change only during a state transition';
    END IF;

    IF OLD.status = 'ready' AND (
        NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.diagnostics IS DISTINCT FROM OLD.diagnostics
        OR NEW.is_active
    ) THEN
        RAISE EXCEPTION 'published retrieval index provenance is immutable';
    END IF;

    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_index_versions_guard
    BEFORE INSERT OR UPDATE OR DELETE ON retrieval_index_versions
    FOR EACH ROW EXECUTE FUNCTION fel_guard_retrieval_index_version();

CREATE FUNCTION fel_guard_retrieval_item() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    index_status text;
    index_corpus_id uuid;
    span_start integer;
    span_end integer;
    row_count integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'retrieval items are immutable';
    END IF;

    SELECT status, corpus_version_id
    INTO index_status, index_corpus_id
    FROM retrieval_index_versions
    WHERE id = NEW.index_version_id
    FOR SHARE;

    IF index_status IS DISTINCT FROM 'building' THEN
        RAISE EXCEPTION 'retrieval items may be added only to a building index';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM corpus_version_documents
        WHERE corpus_version_id = index_corpus_id
          AND document_version_id = NEW.document_version_id
    ) THEN
        RAISE EXCEPTION 'retrieval item document version is not in the index corpus';
    END IF;

    SELECT start_char, end_char INTO span_start, span_end
    FROM source_spans
    WHERE id = NEW.source_span_id
      AND document_version_id = NEW.document_version_id
      AND section_id = NEW.section_id;

    IF span_start IS NULL
       OR NEW.start_char < span_start
       OR NEW.end_char > span_end THEN
        RAISE EXCEPTION 'retrieval item offsets must lie within its source span';
    END IF;

    IF NEW.kind = 'table_row' THEN
        SELECT jsonb_array_length(rows) INTO row_count
        FROM tables_meta
        WHERE id = NEW.table_id
          AND document_version_id = NEW.document_version_id
          AND section_id = NEW.section_id;
        IF row_count IS NULL OR NEW.table_row_index >= row_count THEN
            RAISE EXCEPTION 'retrieval table-row anchor is outside the source table';
        END IF;
    END IF;

    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_items_guard
    BEFORE INSERT OR UPDATE OR DELETE ON retrieval_items
    FOR EACH ROW EXECUTE FUNCTION fel_guard_retrieval_item();

CREATE FUNCTION fel_guard_retrieval_embedding() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    index_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'retrieval embeddings are immutable';
    END IF;
    SELECT status INTO index_status
    FROM retrieval_index_versions
    WHERE id = NEW.index_version_id
    FOR SHARE;
    IF index_status IS DISTINCT FROM 'building' THEN
        RAISE EXCEPTION 'retrieval embeddings may be added only to a building index';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_embeddings_guard
    BEFORE INSERT OR UPDATE OR DELETE ON retrieval_embeddings
    FOR EACH ROW EXECUTE FUNCTION fel_guard_retrieval_embedding();

CREATE FUNCTION fel_guard_query() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    index_status text;
    index_published_at timestamptz;
    workspace_cutoff timestamptz;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'queries are immutable';
    END IF;
    SELECT status, published_at INTO index_status, index_published_at
    FROM retrieval_index_versions
    WHERE id = NEW.index_version_id
    FOR SHARE;
    IF index_status NOT IN ('ready', 'superseded')
       OR index_published_at IS NULL THEN
        RAISE EXCEPTION 'queries must pin a published retrieval index';
    END IF;
    SELECT as_of INTO workspace_cutoff
    FROM workspaces
    WHERE id = NEW.workspace_id AND org_id = NEW.org_id;
    IF workspace_cutoff IS NOT NULL
       AND NEW.effective_as_of > workspace_cutoff THEN
        RAISE EXCEPTION 'query cutoff cannot exceed its workspace cutoff';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER queries_guard
    BEFORE INSERT OR UPDATE ON queries
    FOR EACH ROW EXECUTE FUNCTION fel_guard_query();

CREATE FUNCTION fel_guard_retrieval_run() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    pinned_provider text;
    pinned_model text;
    pinned_planner text;
    expected_terminal_event text;
    latest_event text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'retrieval runs cannot be deleted';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.finished_at IS NOT NULL THEN
            RAISE EXCEPTION 'retrieval runs must start queued and unfinished';
        END IF;
        SELECT riv.embedding_provider, riv.embedding_model, q.planner_version
        INTO pinned_provider, pinned_model, pinned_planner
        FROM queries q
        JOIN retrieval_index_versions riv ON riv.id = q.index_version_id
        WHERE q.id = NEW.query_id AND q.org_id = NEW.org_id;
        IF ROW(NEW.embedding_provider, NEW.embedding_model, NEW.planner_version)
           IS DISTINCT FROM ROW(pinned_provider, pinned_model, pinned_planner) THEN
            RAISE EXCEPTION 'retrieval run provider/model/planner pins disagree with its query';
        END IF;
        RETURN NEW;
    END IF;

    IF ROW(NEW.id, NEW.org_id, NEW.query_id, NEW.parent_run_id, NEW.mode,
           NEW.config_hash, NEW.embedding_provider, NEW.embedding_model,
           NEW.generation_provider, NEW.generation_model, NEW.planner_version,
           NEW.started_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.org_id, OLD.query_id, OLD.parent_run_id, OLD.mode,
           OLD.config_hash, OLD.embedding_provider, OLD.embedding_model,
           OLD.generation_provider, OLD.generation_model, OLD.planner_version,
           OLD.started_at) THEN
        RAISE EXCEPTION 'retrieval run identity and lineage are immutable';
    END IF;

    IF OLD.status IN ('succeeded', 'abstained', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'terminal retrieval runs are immutable';
    END IF;

    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'queued' AND NEW.status = 'planning')
        OR (OLD.status = 'planning' AND NEW.status = 'retrieving')
        OR (OLD.status = 'retrieving' AND NEW.status = 'fusing')
        OR (OLD.status = 'fusing' AND NEW.status = 'generating')
        OR (OLD.status = 'generating' AND NEW.status = 'verifying')
        OR (OLD.status = 'verifying' AND NEW.status IN ('succeeded', 'abstained'))
        OR NEW.status IN ('failed', 'cancelled')
    ) THEN
        RAISE EXCEPTION 'illegal retrieval run transition: % -> %',
            OLD.status, NEW.status;
    END IF;
    expected_terminal_event := CASE NEW.status
        WHEN 'succeeded' THEN 'run_completed'
        WHEN 'abstained' THEN 'run_abstained'
        WHEN 'failed' THEN 'run_failed'
        WHEN 'cancelled' THEN 'run_cancelled'
        ELSE NULL
    END;
    IF NEW.status IS DISTINCT FROM OLD.status
       AND expected_terminal_event IS NOT NULL THEN
        SELECT event_type INTO latest_event
        FROM retrieval_events
        WHERE run_id = NEW.id
        ORDER BY seq DESC
        LIMIT 1;
        IF latest_event IS DISTINCT FROM expected_terminal_event THEN
            RAISE EXCEPTION 'terminal run status % requires final event %',
                NEW.status, expected_terminal_event;
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_runs_guard
    BEFORE INSERT OR UPDATE OR DELETE ON retrieval_runs
    FOR EACH ROW EXECUTE FUNCTION fel_guard_retrieval_run();

CREATE FUNCTION fel_reject_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

CREATE FUNCTION fel_assert_run_open(child_run_id uuid, child_org_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    run_status text;
BEGIN
    SELECT status INTO run_status
    FROM retrieval_runs
    WHERE id = child_run_id AND org_id = child_org_id
    FOR SHARE;
    IF run_status IS NULL THEN
        RAISE EXCEPTION 'run child has no same-organization run';
    END IF;
    IF run_status IN ('succeeded', 'abstained', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'cannot append run child after its run is terminal';
    END IF;
END
$$;

CREATE FUNCTION fel_guard_run_child() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM fel_assert_run_open(NEW.run_id, NEW.org_id);
    RETURN NEW;
END
$$;

CREATE FUNCTION fel_guard_retrieval_event() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    run_status text;
    expected_seq bigint;
BEGIN
    SELECT status INTO run_status
    FROM retrieval_runs
    WHERE id = NEW.run_id AND org_id = NEW.org_id
    FOR UPDATE;
    IF run_status IS NULL THEN
        RAISE EXCEPTION 'event has no same-organization run';
    END IF;
    IF run_status IN ('succeeded', 'abstained', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'cannot append event after its run is terminal';
    END IF;
    SELECT COALESCE(max(seq), 0) + 1 INTO expected_seq
    FROM retrieval_events
    WHERE run_id = NEW.run_id;
    IF NEW.seq <> expected_seq THEN
        RAISE EXCEPTION 'event sequence must be %, got %', expected_seq, NEW.seq;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_events_insert_guard
    BEFORE INSERT ON retrieval_events
    FOR EACH ROW EXECUTE FUNCTION fel_guard_retrieval_event();
CREATE TRIGGER retrieval_events_append_only
    BEFORE UPDATE OR DELETE ON retrieval_events
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_mutation();

CREATE FUNCTION fel_guard_candidate() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    run_index_id uuid;
    item_index_id uuid;
    effective_cutoff timestamptz;
    item_published_at timestamptz;
BEGIN
    PERFORM fel_assert_run_open(NEW.run_id, NEW.org_id);
    SELECT q.index_version_id, q.effective_as_of
    INTO run_index_id, effective_cutoff
    FROM retrieval_runs r
    JOIN queries q ON q.id = r.query_id AND q.org_id = r.org_id
    WHERE r.id = NEW.run_id AND r.org_id = NEW.org_id;
    SELECT ri.index_version_id, d.published_at
    INTO item_index_id, item_published_at
    FROM retrieval_items ri
    JOIN documents d ON d.id = ri.document_id
    WHERE ri.id = NEW.retrieval_item_id;
    IF run_index_id IS DISTINCT FROM item_index_id THEN
        RAISE EXCEPTION 'candidate item index disagrees with its run query';
    END IF;
    IF item_published_at > effective_cutoff THEN
        RAISE EXCEPTION 'candidate evidence was published after the query cutoff';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_candidates_insert_guard
    BEFORE INSERT ON retrieval_candidates
    FOR EACH ROW EXECUTE FUNCTION fel_guard_candidate();
CREATE TRIGGER retrieval_candidates_append_only
    BEFORE UPDATE OR DELETE ON retrieval_candidates
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_mutation();

CREATE FUNCTION fel_guard_feedback() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM retrieval_candidates
        WHERE run_id = NEW.run_id
          AND org_id = NEW.org_id
          AND retrieval_item_id = NEW.retrieval_item_id
    ) THEN
        RAISE EXCEPTION 'feedback item must be a candidate from the same run';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER retrieval_feedback_insert_guard
    BEFORE INSERT ON retrieval_feedback
    FOR EACH ROW EXECUTE FUNCTION fel_guard_feedback();
CREATE TRIGGER retrieval_feedback_append_only
    BEFORE UPDATE OR DELETE ON retrieval_feedback
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_mutation();

CREATE TRIGGER claims_insert_guard
    BEFORE INSERT ON claims
    FOR EACH ROW EXECUTE FUNCTION fel_guard_run_child();
CREATE TRIGGER claims_append_only
    BEFORE UPDATE OR DELETE ON claims
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_mutation();

CREATE FUNCTION fel_guard_citation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    PERFORM fel_assert_run_open(NEW.run_id, NEW.org_id);
    IF NOT EXISTS (
        SELECT 1 FROM retrieval_candidates
        WHERE run_id = NEW.run_id
          AND org_id = NEW.org_id
          AND retrieval_item_id = NEW.retrieval_item_id
          AND accepted
    ) THEN
        RAISE EXCEPTION 'citation item must be accepted by the same run';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER citations_insert_guard
    BEFORE INSERT ON citations
    FOR EACH ROW EXECUTE FUNCTION fel_guard_citation();
CREATE TRIGGER citations_append_only
    BEFORE UPDATE OR DELETE ON citations
    FOR EACH ROW EXECUTE FUNCTION fel_reject_append_only_mutation();

-- fel_app grants: shared artifacts SELECT-only (above); tenant writes are
-- insert (and run status updates) only — never DELETE; append-only tables
-- never receive UPDATE.
GRANT SELECT, INSERT ON queries TO fel_app;
GRANT SELECT, INSERT ON retrieval_runs TO fel_app;
GRANT UPDATE (
    status, budget_usage, cost_usd, timings_ms, finished_at, error
) ON retrieval_runs TO fel_app;
GRANT SELECT, INSERT ON retrieval_events, retrieval_candidates,
    retrieval_feedback, claims, citations TO fel_app;

ALTER TABLE queries ENABLE ROW LEVEL SECURITY;
CREATE POLICY queries_isolation ON queries
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE retrieval_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY retrieval_runs_isolation ON retrieval_runs
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE retrieval_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY retrieval_events_isolation ON retrieval_events
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE retrieval_candidates ENABLE ROW LEVEL SECURITY;
CREATE POLICY retrieval_candidates_isolation ON retrieval_candidates
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE retrieval_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY retrieval_feedback_isolation ON retrieval_feedback
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE claims ENABLE ROW LEVEL SECURITY;
CREATE POLICY claims_isolation ON claims
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());

ALTER TABLE citations ENABLE ROW LEVEL SECURITY;
CREATE POLICY citations_isolation ON citations
    USING (org_id = fel_claim_org_id())
    WITH CHECK (org_id = fel_claim_org_id());
