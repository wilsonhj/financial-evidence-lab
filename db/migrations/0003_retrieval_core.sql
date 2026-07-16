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

-- Supporting unique indexes so retrieval_items can enforce span/section
-- version agreement via composite foreign keys (additive; 0002 PKs unchanged).
CREATE UNIQUE INDEX source_spans_id_version_uniq
    ON source_spans (id, document_version_id);
CREATE UNIQUE INDEX sections_id_version_uniq
    ON sections (id, document_version_id);

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
    )
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
    FOREIGN KEY (section_id, document_version_id)
        REFERENCES sections (id, document_version_id)
);

CREATE UNIQUE INDEX retrieval_items_anchor_uniq
    ON retrieval_items (index_version_id, kind, source_anchor, content_sha256);
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
    retrieval_item_id uuid NOT NULL REFERENCES retrieval_items (id),
    index_version_id uuid NOT NULL REFERENCES retrieval_index_versions (id),
    provider text NOT NULL,
    model text NOT NULL,
    dimensions integer NOT NULL DEFAULT 512 CHECK (dimensions = 512),
    embedding halfvec(512) NOT NULL,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (retrieval_item_id, provider, model, dimensions)
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
    workspace_id uuid NOT NULL REFERENCES workspaces (id),
    created_by uuid NOT NULL,
    question text NOT NULL CHECK (char_length(question) BETWEEN 1 AND 4000),
    effective_as_of timestamptz NOT NULL,
    corpus_version_id uuid REFERENCES corpus_versions (id),
    index_version_id uuid NOT NULL REFERENCES retrieval_index_versions (id),
    plan jsonb NOT NULL,
    planner_version text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    parent_query_id uuid REFERENCES queries (id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX queries_org_workspace_idx ON queries (org_id, workspace_id, created_at);
CREATE INDEX queries_parent_idx ON queries (parent_query_id)
    WHERE parent_query_id IS NOT NULL;

-- Retrieval run status machine (ADR-0006). Stored-trace replay does not
-- insert a row; unchanged rerun creates a child with parent_run_id.
CREATE TABLE retrieval_runs (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    query_id uuid NOT NULL REFERENCES queries (id),
    parent_run_id uuid REFERENCES retrieval_runs (id),
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
    CHECK (
        (status IN ('succeeded', 'abstained', 'failed', 'cancelled')
            AND finished_at IS NOT NULL)
        OR (status NOT IN ('succeeded', 'abstained', 'failed', 'cancelled')
            AND finished_at IS NULL)
    )
);
CREATE INDEX retrieval_runs_org_query_idx
    ON retrieval_runs (org_id, query_id, started_at);
CREATE INDEX retrieval_runs_parent_idx
    ON retrieval_runs (parent_run_id)
    WHERE parent_run_id IS NOT NULL;

-- Append-only ordered events; SSE event id is decimal seq.
CREATE TABLE retrieval_events (
    run_id uuid NOT NULL REFERENCES retrieval_runs (id),
    org_id uuid NOT NULL REFERENCES organizations (id),
    seq bigint NOT NULL CHECK (seq >= 1),
    event_type text NOT NULL CHECK (event_type IN (
        'run_started', 'plan_ready', 'lane_started', 'candidate_batch',
        'lane_completed', 'fusion_completed', 'rerank_completed',
        'context_selected', 'claim_generated', 'citation_verified',
        'run_abstained', 'run_completed', 'run_failed', 'heartbeat'
    )),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX retrieval_events_org_idx ON retrieval_events (org_id, created_at);

-- Per-lane candidate contributions retained for Observatory replay.
CREATE TABLE retrieval_candidates (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL REFERENCES retrieval_runs (id),
    retrieval_item_id uuid NOT NULL REFERENCES retrieval_items (id),
    lane text NOT NULL CHECK (lane IN ('dense', 'lexical', 'facts', 'tables')),
    variant_index integer NOT NULL CHECK (variant_index BETWEEN 0 AND 3),
    lane_rank integer NOT NULL CHECK (lane_rank >= 1),
    raw_score text NOT NULL,
    normalized_score text,
    rrf_contribution text NOT NULL,
    fused_rank integer CHECK (fused_rank IS NULL OR fused_rank >= 1),
    rerank_rank integer CHECK (rerank_rank IS NULL OR rerank_rank >= 1),
    accepted boolean NOT NULL,
    rejection_code text,
    decision_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    timing_ms integer NOT NULL CHECK (timing_ms >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, lane, variant_index, retrieval_item_id)
);
CREATE INDEX retrieval_candidates_org_run_idx
    ON retrieval_candidates (org_id, run_id);

CREATE TABLE retrieval_feedback (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL REFERENCES retrieval_runs (id),
    retrieval_item_id uuid NOT NULL REFERENCES retrieval_items (id),
    label text NOT NULL CHECK (label IN (
        'relevant', 'irrelevant', 'duplicate', 'temporally_invalid'
    )),
    actor_user_id uuid NOT NULL,
    reason text CHECK (reason IS NULL OR char_length(reason) <= 2000),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX retrieval_feedback_org_run_idx
    ON retrieval_feedback (org_id, run_id);

-- Retrieval-produced claims (distinct from the frozen claim/v1 JSON shape
-- used elsewhere; DB rows carry org/run provenance for Observatory).
CREATE TABLE claims (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    run_id uuid NOT NULL REFERENCES retrieval_runs (id),
    ord integer NOT NULL CHECK (ord >= 0),
    text text NOT NULL,
    status text NOT NULL CHECK (status IN (
        'supported', 'partially_supported', 'contradicted',
        'derived', 'unsupported'
    )),
    confidence text,
    calculation_lineage jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, ord)
);
CREATE INDEX claims_org_run_idx ON claims (org_id, run_id);

CREATE TABLE citations (
    id uuid PRIMARY KEY,
    org_id uuid NOT NULL REFERENCES organizations (id),
    claim_id uuid NOT NULL REFERENCES claims (id),
    retrieval_item_id uuid NOT NULL REFERENCES retrieval_items (id),
    source_span_id uuid NOT NULL REFERENCES source_spans (id),
    status text NOT NULL CHECK (status IN (
        'entailed', 'partial', 'contradictory', 'irrelevant'
    )),
    verifier text,
    model text,
    version text,
    numeric_checks jsonb NOT NULL DEFAULT '{}'::jsonb,
    rationale text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX citations_org_claim_idx ON citations (org_id, claim_id);

-- fel_app grants: shared artifacts SELECT-only (above); tenant writes are
-- insert (and run status updates) only — never DELETE; append-only tables
-- never receive UPDATE.
GRANT SELECT, INSERT ON queries TO fel_app;
GRANT SELECT, INSERT, UPDATE ON retrieval_runs TO fel_app;
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
