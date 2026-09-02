-- Harness for 0008_worker_role.sql (issue #190, ADR-0013).
--
-- Superuser-only coverage cannot catch a privilege bug (the 0005 bug class),
-- and for the worker role the failure mode is worse than for fel_app: a
-- missing grant does not fail a request, it fails a JOB, which retries,
-- exhausts its attempts and lands in the queue's error column hours later.
-- So every table class the worker writes is exercised HERE under
-- `SET LOCAL ROLE fel_worker`, and the boundaries the role exists to enforce
-- (no DELETE anywhere, no DDL) are asserted to raise 42501.
--
-- Structure: seed the rows only a privileged path may create (organizations,
-- workspaces, extraction runs) as the migration superuser, then drop into
-- fel_worker for every write the job path actually performs.

\set ON_ERROR_STOP on

BEGIN;

\ir _helpers.sql

-- ---------------------------------------------------------------------------
-- Superuser seed: request-path rows the worker never creates.
-- ---------------------------------------------------------------------------

INSERT INTO organizations (id, name)
VALUES ('00000000-0000-0000-0000-0000000009a1', 'Worker Role Org');
INSERT INTO memberships (org_id, user_id, role)
VALUES ('00000000-0000-0000-0000-0000000009a1', '00000000-0000-0000-0000-0000000009b1', 'owner');
INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, fiscal_calendar, as_of)
VALUES (
    '00000000-0000-0000-0000-0000000009c1',
    '00000000-0000-0000-0000-0000000009a1',
    'Worker WS',
    '00000000-0000-0000-0000-0000000009d1',
    'USD', 'calendar', now()
);
INSERT INTO extraction_policies (id, org_id, version, created_by)
VALUES (
    '00000000-0000-0000-0000-0000000009e1',
    '00000000-0000-0000-0000-0000000009a1', 1,
    '00000000-0000-0000-0000-0000000009b1'
);
INSERT INTO corpus_versions (id, label, status)
VALUES ('00000000-0000-0000-0000-000000000901', 'Seed corpus', 'draft');
INSERT INTO extraction_runs (
    id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
    ontology_version, workflow_version, provider, model, policy_id,
    input_hash, idempotency_key, created_by
) VALUES (
    '00000000-0000-0000-0000-0000000009f1',
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-0000000009c1',
    '00000000-0000-0000-0000-0000000009d1',
    ARRAY['kpi']::text[], now(),
    '00000000-0000-0000-0000-000000000901',
    'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
    '00000000-0000-0000-0000-0000000009e1',
    'sha256:0000000000000000000000000000000000000000000000000000000000000001',
    'idem-worker-1', '00000000-0000-0000-0000-0000000009b1'
);

-- A queued job for the worker to claim, and a document the ingestion path
-- will link its parsed version to.
INSERT INTO jobs (id, kind, queue, payload, org_id)
VALUES (
    '00000000-0000-0000-0000-000000000801', 'sec_filing_fetch', 'ingestion',
    '{}'::jsonb, '00000000-0000-0000-0000-0000000009a1'
);

-- ---------------------------------------------------------------------------
-- As fel_worker: one representative write per granted table class.
-- ---------------------------------------------------------------------------

SET LOCAL ROLE fel_worker;

-- Queue: claim (UPDATE) and enqueue (INSERT) — the consumer's whole lifecycle
-- runs through these two privileges plus SELECT.
UPDATE jobs
   SET status = 'running', attempts = attempts + 1,
       lease = gen_random_uuid(), heartbeat_at = now()
 WHERE id = '00000000-0000-0000-0000-000000000801';
INSERT INTO jobs (id, kind, queue, payload, org_id)
VALUES (
    '00000000-0000-0000-0000-000000000802', 'sec_filing_fetch', 'ingestion',
    '{}'::jsonb, '00000000-0000-0000-0000-0000000009a1'
);
-- Platform jobs carry no tenant; the worker must still be able to enqueue them.
INSERT INTO jobs (id, kind, queue, payload)
VALUES ('00000000-0000-0000-0000-000000000803', 'sec_discovery', 'ingestion', '{}'::jsonb);

-- Corpus: the ingestion pipeline's document -> version -> section -> span ->
-- table -> fact chain, its quarantine sink, and its idempotent run ledger.
INSERT INTO documents (
    id, entity_id, accession, source_url, content_hash, storage_key, published_at
) VALUES (
    '00000000-0000-0000-0000-000000000701',
    '00000000-0000-0000-0000-0000000009d1',
    'worker-a1', 'https://example.test/worker-a1',
    'sha256:0000000000000000000000000000000000000000000000000000000000000011',
    'raw/sha256/0000000000000000000000000000000000000000000000000000000000000011',
    now()
);
INSERT INTO document_versions (
    id, document_id, parser_version, normalizer_version, canonical_text_key
) VALUES (
    '00000000-0000-0000-0000-000000000702',
    '00000000-0000-0000-0000-000000000701', 'p1', 'n1', 'text/sha256/aa'
);
INSERT INTO sections (
    id, document_version_id, heading, heading_path, ord, start_char, end_char
) VALUES (
    '00000000-0000-0000-0000-000000000703',
    '00000000-0000-0000-0000-000000000702', 'ITEM 8', ARRAY['ITEM 8'], 0, 0, 400
);
INSERT INTO source_spans (
    id, document_version_id, section_id, start_char, end_char, text_hash
) VALUES (
    '00000000-0000-0000-0000-000000000704',
    '00000000-0000-0000-0000-000000000702',
    '00000000-0000-0000-0000-000000000703',
    0, 400,
    'sha256:0000000000000000000000000000000000000000000000000000000000000012'
);
INSERT INTO tables_meta (id, document_version_id, section_id, ord, headers, rows)
VALUES (
    '00000000-0000-0000-0000-000000000705',
    '00000000-0000-0000-0000-000000000702',
    '00000000-0000-0000-0000-000000000703',
    0, '["a"]'::jsonb, '[["1"]]'::jsonb
);
INSERT INTO financial_facts (
    id, entity_id, document_version_id, concept, value, unit, period_type,
    period_end, source_span_id, fact_key
) VALUES (
    '00000000-0000-0000-0000-000000000706',
    '00000000-0000-0000-0000-0000000009d1',
    '00000000-0000-0000-0000-000000000702',
    'Revenues', '100', 'USD', 'duration', DATE '2026-06-30',
    '00000000-0000-0000-0000-000000000704', 'revenues:2026Q2:USD'
);
INSERT INTO ingestion_quarantine (id, accession, reason_code, diagnostic)
VALUES (
    '00000000-0000-0000-0000-000000000707', 'worker-bad',
    'DIVERGENT_ACCESSION_CONTENT', 'bytes differ from the recorded accession'
);
INSERT INTO ingestion_runs (
    job_key, source_hash, parser_version, normalizer_version, status
) VALUES (
    'worker-a1:p1:n1',
    'sha256:0000000000000000000000000000000000000000000000000000000000000011',
    'p1', 'n1', 'running'
);
UPDATE ingestion_runs
   SET status = 'succeeded',
       document_id = '00000000-0000-0000-0000-000000000701',
       document_version_id = '00000000-0000-0000-0000-000000000702'
 WHERE job_key = 'worker-a1:p1:n1';

-- Corpus publication: mint a version, attach the parsed document, flip it
-- active. The whole publish transaction is a worker path.
INSERT INTO corpus_versions (id, label, status)
VALUES ('00000000-0000-0000-0000-000000000902', 'Worker corpus', 'draft');
INSERT INTO corpus_version_documents (corpus_version_id, document_version_id)
VALUES (
    '00000000-0000-0000-0000-000000000902',
    '00000000-0000-0000-0000-000000000702'
);
UPDATE corpus_versions
   SET status = 'active', is_active = true, published_at = now()
 WHERE id = '00000000-0000-0000-0000-000000000902';

-- Retrieval index build: draft -> building, append items and embeddings
-- (both guards take FOR SHARE on retrieval_index_versions, which is legal
-- only because of the UPDATE grant), then publish ready.
INSERT INTO retrieval_index_versions (
    id, corpus_version_id, chunker_version, config_hash,
    embedding_provider, embedding_model
) VALUES (
    '00000000-0000-0000-0000-000000000a01',
    '00000000-0000-0000-0000-000000000902', 'chunker-v1',
    'sha256:0000000000000000000000000000000000000000000000000000000000000013',
    'mock', 'mock-embed-v1'
);
UPDATE retrieval_index_versions SET status = 'building'
 WHERE id = '00000000-0000-0000-0000-000000000a01';
INSERT INTO retrieval_items (
    id, index_version_id, kind, entity_id, document_id, document_version_id,
    section_id, source_span_id, content, content_sha256, start_char, end_char,
    token_count
) VALUES (
    '00000000-0000-0000-0000-000000000a02',
    '00000000-0000-0000-0000-000000000a01', 'passage',
    '00000000-0000-0000-0000-0000000009d1',
    '00000000-0000-0000-0000-000000000701',
    '00000000-0000-0000-0000-000000000702',
    '00000000-0000-0000-0000-000000000703',
    '00000000-0000-0000-0000-000000000704',
    'Revenue was $100 million.',
    'sha256:0000000000000000000000000000000000000000000000000000000000000014',
    0, 400, 6
);
INSERT INTO retrieval_embeddings (
    retrieval_item_id, index_version_id, provider, model, embedding, content_sha256
) VALUES (
    '00000000-0000-0000-0000-000000000a02',
    '00000000-0000-0000-0000-000000000a01', 'mock', 'mock-embed-v1',
    array_fill(0.1::real, ARRAY[512])::halfvec(512),
    'sha256:0000000000000000000000000000000000000000000000000000000000000014'
);
UPDATE retrieval_index_versions SET status = 'ready', published_at = now()
 WHERE id = '00000000-0000-0000-0000-000000000a01';

-- Extraction: advance the run, then write every child row the persist stage
-- writes. Each child insert passes through fel_assert_extraction_run_open,
-- whose FOR SHARE on extraction_runs is legal only because of the
-- column-level UPDATE grant on that table.
UPDATE extraction_runs
   SET status = 'running', started_at = now()
 WHERE id = '00000000-0000-0000-0000-0000000009f1';
INSERT INTO extraction_run_steps (
    id, org_id, run_id, step_name, attempt, status, input_hash,
    workflow_version, schema_version, prompt_version
) VALUES (
    '00000000-0000-0000-0000-000000000b01',
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-0000000009f1',
    'extract', 1, 'running',
    'sha256:0000000000000000000000000000000000000000000000000000000000000015',
    'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
);
UPDATE extraction_run_steps
   SET status = 'succeeded',
       output_hash = 'sha256:0000000000000000000000000000000000000000000000000000000000000016',
       finished_at = now()
 WHERE id = '00000000-0000-0000-0000-000000000b01';
INSERT INTO extraction_run_events (org_id, run_id, event_type, payload)
VALUES (
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-0000000009f1',
    'step_completed', '{}'::jsonb
);
INSERT INTO extraction_proposals (
    id, org_id, workspace_id, run_id, kind, metric_id, payload,
    raw_payload_hash, definition_hash, record_confidence, state
) VALUES (
    '00000000-0000-0000-0000-000000000b02',
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-0000000009c1',
    '00000000-0000-0000-0000-0000000009f1',
    'kpi', 'arr', '{}'::jsonb,
    'sha256:0000000000000000000000000000000000000000000000000000000000000017',
    'sha256:0000000000000000000000000000000000000000000000000000000000000018',
    0.900, 'needs_review'
),
(
    '00000000-0000-0000-0000-000000000b03',
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-0000000009c1',
    '00000000-0000-0000-0000-0000000009f1',
    'kpi', 'arr', '{}'::jsonb,
    'sha256:0000000000000000000000000000000000000000000000000000000000000019',
    'sha256:0000000000000000000000000000000000000000000000000000000000000018',
    0.800, 'needs_review'
);
INSERT INTO extraction_proposal_evidence (
    org_id, proposal_id, source_span_id, document_version_id, role, citation_status
) VALUES (
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-000000000b02',
    '00000000-0000-0000-0000-000000000704',
    '00000000-0000-0000-0000-000000000702',
    'supports', 'verified'
);
INSERT INTO extraction_conflicts (id, org_id, workspace_id, conflict_key, reason_codes)
VALUES (
    '00000000-0000-0000-0000-000000000b04',
    '00000000-0000-0000-0000-0000000009a1',
    '00000000-0000-0000-0000-0000000009c1',
    'arr:2026Q2', ARRAY['value_mismatch']::text[]
);
INSERT INTO extraction_conflict_members (conflict_id, proposal_id, org_id)
VALUES
    ('00000000-0000-0000-0000-000000000b04', '00000000-0000-0000-0000-000000000b02',
     '00000000-0000-0000-0000-0000000009a1'),
    ('00000000-0000-0000-0000-000000000b04', '00000000-0000-0000-0000-000000000b03',
     '00000000-0000-0000-0000-0000000009a1');

-- ---------------------------------------------------------------------------
-- Boundaries: no DELETE anywhere, no DDL. 42501 = insufficient_privilege,
-- i.e. the GRANT is missing — not a trigger raising P0001, which would still
-- leave the privilege in place for a table whose guard is later relaxed.
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_rejection('worker cannot delete jobs', $sql$
    DELETE FROM jobs WHERE id = '00000000-0000-0000-0000-000000000802'
$sql$, ARRAY['42501']);

SELECT pg_temp.expect_rejection('worker cannot delete corpus documents', $sql$
    DELETE FROM documents WHERE id = '00000000-0000-0000-0000-000000000701'
$sql$, ARRAY['42501']);

SELECT pg_temp.expect_rejection('worker cannot delete corpus versions', $sql$
    DELETE FROM corpus_versions WHERE id = '00000000-0000-0000-0000-000000000902'
$sql$, ARRAY['42501']);

SELECT pg_temp.expect_rejection('worker cannot delete extraction proposals', $sql$
    DELETE FROM extraction_proposals WHERE id = '00000000-0000-0000-0000-000000000b02'
$sql$, ARRAY['42501']);

SELECT pg_temp.expect_rejection('worker cannot run DDL on jobs', $sql$
    ALTER TABLE jobs ADD COLUMN worker_injected text
$sql$, ARRAY['42501']);

SELECT pg_temp.expect_rejection('worker cannot run DDL on corpus tables', $sql$
    ALTER TABLE documents ADD COLUMN worker_injected text
$sql$, ARRAY['42501']);

SELECT pg_temp.expect_rejection('worker cannot create tables', $sql$
    CREATE TABLE worker_injected (id uuid PRIMARY KEY)
$sql$, ARRAY['42501']);

-- The worker never creates tenants or workspaces; those are request-path rows.
SELECT pg_temp.expect_rejection('worker cannot insert organizations', $sql$
    INSERT INTO organizations (id, name)
    VALUES ('00000000-0000-0000-0000-0000000009a9', 'Rogue Org')
$sql$, ARRAY['42501']);
SELECT pg_temp.expect_rejection('worker cannot insert workspaces', $sql$
    INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, fiscal_calendar, as_of)
    VALUES (
        '00000000-0000-0000-0000-0000000009c9',
        '00000000-0000-0000-0000-0000000009a1',
        'Rogue WS', '00000000-0000-0000-0000-0000000009d1', 'USD', 'calendar', now()
    )
$sql$, ARRAY['42501']);

-- Org consistency is what the worker's RLS policies pin: a child row whose
-- org_id disagrees with its parent run cannot be written. Two independent
-- mechanisms refuse it and the BEFORE trigger simply gets there first
-- (P0001, from fel_assert_extraction_run_open); the 0008 policy's WITH CHECK
-- would refuse the same row with 42501 if the guard were ever relaxed.
SELECT pg_temp.expect_rejection('worker cannot write a step under a mismatched org', $sql$
    INSERT INTO extraction_run_steps (
        id, org_id, run_id, step_name, attempt, status, input_hash,
        workflow_version, schema_version, prompt_version
    ) VALUES (
        '00000000-0000-0000-0000-000000000b09',
        '00000000-0000-0000-0000-0000000009a9',
        '00000000-0000-0000-0000-0000000009f1',
        'extract', 2, 'running',
        'sha256:000000000000000000000000000000000000000000000000000000000000001a',
        'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
    )
$sql$, ARRAY['42501', 'P0001']);

DO $$
BEGIN
    IF (SELECT count(*) FROM extraction_run_steps
        WHERE run_id = '00000000-0000-0000-0000-0000000009f1') <> 1
       OR (SELECT count(*) FROM extraction_proposals
           WHERE run_id = '00000000-0000-0000-0000-0000000009f1') <> 2
       OR (SELECT count(*) FROM extraction_conflict_members
           WHERE conflict_id = '00000000-0000-0000-0000-000000000b04') <> 2
       OR (SELECT count(*) FROM retrieval_items
           WHERE index_version_id = '00000000-0000-0000-0000-000000000a01') <> 1
       OR (SELECT count(*) FROM financial_facts
           WHERE id = '00000000-0000-0000-0000-000000000706') <> 1
       OR (SELECT status FROM jobs WHERE id = '00000000-0000-0000-0000-000000000801')
          <> 'running' THEN
        RAISE EXCEPTION 'not ok - fel_worker write path did not persist';
    END IF;
    RAISE NOTICE 'ok - fel_worker queue claim/enqueue';
    RAISE NOTICE 'ok - fel_worker corpus ingest + publish + run ledger';
    RAISE NOTICE 'ok - fel_worker retrieval index build (items + embeddings)';
    RAISE NOTICE 'ok - fel_worker extraction run advance + child writes';
END
$$;

RESET ROLE;

DO $$
BEGIN
    RAISE NOTICE 'ok - all worker-role cases passed';
END
$$;

ROLLBACK;
