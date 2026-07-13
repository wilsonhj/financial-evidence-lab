-- Corpus core: immutable documents, parsed versions, hierarchy, source spans,
-- tables, normalized facts, atomic corpus publication, quarantine, and the
-- idempotent ingestion-run ledger (M1-INGESTION, T0101-T0106).
--
-- Tenancy rationale: corpus data is PUBLIC, SHARED evidence (SEC filings,
-- macro series). It carries no org_id and no RLS by design — every tenant
-- reads the same immutable corpus, and tenant isolation applies to analysis
-- objects (workspaces, claims, extractions), never to public source
-- evidence. The API role (fel_app) is granted SELECT only; all writes happen
-- in workers running under the service role, which keeps the corpus
-- append-only from the application's point of view.
--
-- Additive-only migration; follows the conventions of 0001_platform_core.sql.
--
-- Provenance invariants:
-- * documents.content_hash ALWAYS matches the bytes every published version
--   of that document was parsed from. A re-fetch of a recorded accession
--   with DIFFERENT bytes never updates the row and never creates a version;
--   it fails closed into ingestion_quarantine with reason code
--   DIVERGENT_ACCESSION_CONTENT (supersede-in-place was rejected: the raw
--   store is immutable evidence).
-- * document_versions.canonical_text_key points at the immutably stored
--   canonical text rendering (content-addressed, text/sha256/<hex>) that
--   section/span character offsets and span text hashes were computed
--   against, so citations re-verify against exactly that text forever.
-- * ingestion_runs rows are claimed up front with status 'running' inside
--   the job transaction (INSERT .. ON CONFLICT DO NOTHING), which
--   serializes concurrent identical jobs on the job_key primary key; the
--   status is always terminal (succeeded/quarantined) once the transaction
--   commits, so a committed 'running' row is unreachable in practice.

-- Immutable source metadata (spec 11.1 `documents`, temporal fields per
-- spec 10.3). One row per discovered source object; raw bytes live in the
-- object store under the content-addressed key.
CREATE TABLE documents (
    id uuid PRIMARY KEY,
    entity_id uuid NOT NULL,
    accession text NOT NULL UNIQUE,
    form text,
    source_url text NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    storage_key text NOT NULL,
    mime_type text NOT NULL DEFAULT 'text/html',
    published_at timestamptz NOT NULL,
    filed_at timestamptz,
    period_start date,
    period_end date,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz
);
-- Point-in-time listing: WHERE entity_id = $1 AND published_at <= $2.
CREATE INDEX documents_entity_published_idx ON documents (entity_id, published_at);
CREATE INDEX documents_content_hash_idx ON documents (content_hash);

-- Parsed/rendered versions of a document (spec 11.1 `document_versions`).
-- A (document, parser_version) pair is parsed at most once.
CREATE TABLE document_versions (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents (id),
    parser_version text NOT NULL,
    normalizer_version text NOT NULL,
    status text NOT NULL DEFAULT 'parsed'
        CHECK (status IN ('parsed', 'quarantined')),
    -- Immutable content-addressed key of the canonical parsed text this
    -- version's span offsets/text hashes reference (see header invariants).
    canonical_text_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, parser_version, normalizer_version)
);

-- Filing hierarchy (spec 11.1 `sections`): heading path plus stable order.
CREATE TABLE sections (
    id uuid PRIMARY KEY,
    document_version_id uuid NOT NULL REFERENCES document_versions (id),
    parent_id uuid REFERENCES sections (id),
    heading text NOT NULL,
    heading_path text[] NOT NULL,
    ord integer NOT NULL CHECK (ord >= 0),
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL,
    CHECK (end_char >= start_char),
    UNIQUE (document_version_id, ord)
);

-- Stable source spans (contract source-span/v1, spec 11.2). Citations point
-- here, never at copied text.
CREATE TABLE source_spans (
    id uuid PRIMARY KEY,
    document_version_id uuid NOT NULL REFERENCES document_versions (id),
    section_id uuid NOT NULL REFERENCES sections (id),
    page integer CHECK (page >= 1),
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL,
    text_hash text NOT NULL CHECK (text_hash ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (end_char >= start_char)
);
CREATE INDEX source_spans_document_version_idx ON source_spans (document_version_id);

-- Extracted tables (spec 11.1 `tables`); cell payloads are JSON arrays of
-- text (structured table_cells indexing is a retrieval-milestone concern).
CREATE TABLE tables_meta (
    id uuid PRIMARY KEY,
    document_version_id uuid NOT NULL REFERENCES document_versions (id),
    section_id uuid NOT NULL REFERENCES sections (id),
    ord integer NOT NULL CHECK (ord >= 0),
    caption text,
    headers jsonb NOT NULL DEFAULT '[]'::jsonb,
    rows jsonb NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (document_version_id, ord)
);

-- Normalized facts (contract financial-fact/v1, spec 11.4). Values are
-- decimal strings end-to-end; binary floats are never authoritative.
CREATE TABLE financial_facts (
    id uuid PRIMARY KEY,
    entity_id uuid NOT NULL,
    document_version_id uuid NOT NULL REFERENCES document_versions (id),
    concept text NOT NULL,
    label text,
    value text NOT NULL CHECK (value ~ '^-?[0-9]+(\.[0-9]+)?$'),
    unit text NOT NULL,
    scale integer NOT NULL DEFAULT 0,
    period_type text NOT NULL CHECK (period_type IN ('instant', 'duration')),
    period_instant date,
    period_start date,
    period_end date,
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_span_id uuid NOT NULL REFERENCES source_spans (id),
    reported_or_derived text NOT NULL DEFAULT 'reported'
        CHECK (reported_or_derived IN ('reported', 'derived')),
    confidence numeric CHECK (confidence >= 0 AND confidence <= 1),
    -- Duplicate detection: a fact that repeats another presentation of the
    -- same (concept, period, unit, dimensions) points at the canonical row.
    duplicate_of uuid REFERENCES financial_facts (id),
    -- Restatement linkage: a later filing's fact that supersedes an earlier
    -- reported value for the same fact key points at the restated row.
    restates uuid REFERENCES financial_facts (id),
    -- Deterministic dedupe key over (concept, period, unit, dimensions).
    fact_key text NOT NULL
);
-- One canonical (non-duplicate) fact per key within a parsed version.
CREATE UNIQUE INDEX financial_facts_canonical_uniq
    ON financial_facts (document_version_id, fact_key)
    WHERE duplicate_of IS NULL;
CREATE INDEX financial_facts_entity_concept_idx ON financial_facts (entity_id, concept);
CREATE INDEX financial_facts_fact_key_idx ON financial_facts (fact_key);

-- Atomic corpus publication (spec 12.2 stage 13). Exactly one active version
-- at a time, enforced by the partial unique index; the publish transaction
-- flips the pointer in a single transaction.
CREATE TABLE corpus_versions (
    id uuid PRIMARY KEY,
    label text NOT NULL,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'superseded')),
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    CHECK (is_active = (status = 'active'))
);
CREATE UNIQUE INDEX corpus_versions_single_active ON corpus_versions ((true))
    WHERE is_active;

CREATE TABLE corpus_version_documents (
    corpus_version_id uuid NOT NULL REFERENCES corpus_versions (id),
    document_version_id uuid NOT NULL REFERENCES document_versions (id),
    PRIMARY KEY (corpus_version_id, document_version_id)
);

-- Quarantine for malformed sources (FR-ING-007): every row carries an
-- actionable diagnostic (stable reason code + operator-readable message).
CREATE TABLE ingestion_quarantine (
    id uuid PRIMARY KEY,
    accession text,
    source_url text,
    content_hash text,
    reason_code text NOT NULL,
    diagnostic text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ingestion_quarantine_accession_idx ON ingestion_quarantine (accession);

-- Idempotent versioned-job ledger (spec 12.4): the job key is derived from
-- (entity, accession, source hash, parser version, normalizer version);
-- re-running an identical job returns the recorded result and performs no
-- writes. 'running' exists only transiently inside the claiming
-- transaction (see header invariants); terminal states are
-- succeeded/quarantined.
CREATE TABLE ingestion_runs (
    job_key text PRIMARY KEY,
    source_hash text NOT NULL,
    parser_version text NOT NULL,
    normalizer_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'quarantined')),
    document_id uuid,
    document_version_id uuid,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- API request paths read the shared corpus evidence tables; only workers
-- (service role, bypasses grants below because it owns the schema) may
-- write it. ingestion_quarantine and ingestion_runs are operational
-- internals no API endpoint reads — deliberately NOT granted (least
-- privilege).
GRANT SELECT ON documents, document_versions, sections, source_spans,
    tables_meta, financial_facts, corpus_versions, corpus_version_documents
    TO fel_app;
