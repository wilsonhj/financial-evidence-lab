\set ON_ERROR_STOP on

BEGIN;

CREATE FUNCTION pg_temp.expect_rejection(
    test_name text,
    statement text,
    expected_states text[] DEFAULT ARRAY['23503', '23514', 'P0001']
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    actual_state text;
BEGIN
    BEGIN
        EXECUTE statement;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE;
        IF actual_state = ANY(expected_states) THEN
            RAISE NOTICE 'ok - % rejected with %', test_name, actual_state;
            RETURN;
        END IF;
        RAISE;
    END;
    RAISE EXCEPTION 'not ok - % was accepted', test_name;
END
$$;

DO $$
DECLARE
    installed_version text;
BEGIN
    SELECT extversion INTO installed_version FROM pg_extension WHERE extname = 'vector';
    IF (split_part(installed_version, '.', 1)::integer,
        split_part(installed_version, '.', 2)::integer,
        split_part(installed_version, '.', 3)::integer) < (0, 8, 2) THEN
        RAISE EXCEPTION 'test requires pgvector >= 0.8.2, found %', installed_version;
    END IF;
END
$$;

INSERT INTO organizations (id, name) VALUES
    ('00000000-0000-0000-0000-000000000101', 'Org 1'),
    ('00000000-0000-0000-0000-000000000102', 'Org 2');
INSERT INTO memberships (org_id, user_id, role) VALUES
    ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000201', 'owner'),
    ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000202', 'owner');
INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, fiscal_calendar, as_of) VALUES
    ('00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000101', 'WS 1', '00000000-0000-0000-0000-000000000401', 'USD', 'calendar', now()),
    ('00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-000000000102', 'WS 2', '00000000-0000-0000-0000-000000000402', 'USD', 'calendar', now());

INSERT INTO documents (
    id, entity_id, accession, source_url, content_hash, storage_key, published_at
) VALUES
    ('00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000401', 'a1', 'https://example.test/a1', 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'a1', now()),
    ('00000000-0000-0000-0000-000000000502', '00000000-0000-0000-0000-000000000402', 'a2', 'https://example.test/a2', 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'a2', now());
INSERT INTO document_versions (
    id, document_id, parser_version, normalizer_version, canonical_text_key
) VALUES
    ('00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000501', 'p1', 'n1', 'text/1'),
    ('00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-000000000502', 'p1', 'n1', 'text/2');
INSERT INTO sections (
    id, document_version_id, heading, heading_path, ord, start_char, end_char
) VALUES
    ('00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-000000000601', 'One', ARRAY['One'], 0, 0, 100),
    ('00000000-0000-0000-0000-000000000702', '00000000-0000-0000-0000-000000000602', 'Two', ARRAY['Two'], 0, 0, 100);
INSERT INTO source_spans (
    id, document_version_id, section_id, start_char, end_char, text_hash
) VALUES
    ('00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', 0, 100, 'sha256:1111111111111111111111111111111111111111111111111111111111111111'),
    ('00000000-0000-0000-0000-000000000802', '00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-000000000702', 0, 100, 'sha256:2222222222222222222222222222222222222222222222222222222222222222');
INSERT INTO financial_facts (
    id, entity_id, document_version_id, concept, value, unit, period_type,
    period_instant, source_span_id, fact_key
) VALUES
    ('00000000-0000-0000-0000-000000000901', '00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000601', 'Revenue', '1', 'USD', 'instant', CURRENT_DATE, '00000000-0000-0000-0000-000000000801', 'f1'),
    ('00000000-0000-0000-0000-000000000902', '00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-000000000602', 'Revenue', '2', 'USD', 'instant', CURRENT_DATE, '00000000-0000-0000-0000-000000000802', 'f2');
INSERT INTO tables_meta (
    id, document_version_id, section_id, ord, rows
) VALUES
    ('00000000-0000-0000-0000-000000000a01', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', 0, '[["one"]]'::jsonb),
    ('00000000-0000-0000-0000-000000000a02', '00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-000000000702', 0, '[["two"]]'::jsonb);

INSERT INTO corpus_versions (id, label, status, is_active, published_at) VALUES
    ('00000000-0000-0000-0000-000000000b01', 'Corpus 1', 'active', true, now()),
    ('00000000-0000-0000-0000-000000000b02', 'Corpus 2', 'superseded', false, now());
INSERT INTO corpus_version_documents (corpus_version_id, document_version_id) VALUES
    ('00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000601'),
    ('00000000-0000-0000-0000-000000000b02', '00000000-0000-0000-0000-000000000602');

INSERT INTO retrieval_index_versions (
    id, corpus_version_id, chunker_version, config_hash,
    embedding_provider, embedding_model
) VALUES
    ('00000000-0000-0000-0000-000000000c01', '00000000-0000-0000-0000-000000000b01', 'v1', 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'openai', 'text-embedding-3-small'),
    ('00000000-0000-0000-0000-000000000c02', '00000000-0000-0000-0000-000000000b02', 'v1', 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'openai', 'text-embedding-3-small'),
    ('00000000-0000-0000-0000-000000000c03', '00000000-0000-0000-0000-000000000b01', 'v2', 'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', 'openai', 'text-embedding-3-small');
UPDATE retrieval_index_versions SET status = 'building';

INSERT INTO retrieval_items (
    id, index_version_id, kind, entity_id, document_id, document_version_id,
    section_id, source_span_id, content, content_sha256,
    start_char, end_char, token_count
) VALUES
    ('00000000-0000-0000-0000-000000000d01', '00000000-0000-0000-0000-000000000c01', 'passage', '00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-000000000801', 'one', 'sha256:1111111111111111111111111111111111111111111111111111111111111111', 0, 100, 1),
    ('00000000-0000-0000-0000-000000000d02', '00000000-0000-0000-0000-000000000c02', 'passage', '00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-000000000502', '00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-000000000702', '00000000-0000-0000-0000-000000000802', 'two', 'sha256:2222222222222222222222222222222222222222222222222222222222222222', 0, 100, 1);
INSERT INTO retrieval_items (
    id, index_version_id, kind, entity_id, document_id, document_version_id,
    section_id, source_span_id, financial_fact_id, content, content_sha256,
    start_char, end_char, token_count
) VALUES (
    '00000000-0000-0000-0000-000000000d03', '00000000-0000-0000-0000-000000000c01', 'fact', '00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-000000000901', 'one fact', 'sha256:3333333333333333333333333333333333333333333333333333333333333333', 0, 100, 2
);
INSERT INTO retrieval_items (
    id, index_version_id, kind, entity_id, document_id, document_version_id,
    section_id, source_span_id, table_id, table_row_index, content,
    content_sha256, start_char, end_char, token_count
) VALUES (
    '00000000-0000-0000-0000-000000000d04', '00000000-0000-0000-0000-000000000c01', 'table_row', '00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-000000000a01', 0, 'one row', 'sha256:4444444444444444444444444444444444444444444444444444444444444444', 0, 100, 2
);

SELECT pg_temp.expect_rejection('cross-corpus item', $sql$
    INSERT INTO retrieval_items (
        id, index_version_id, kind, entity_id, document_id, document_version_id,
        section_id, source_span_id, content, content_sha256,
        start_char, end_char, token_count
    ) VALUES (
        '00000000-0000-0000-0000-000000000d11', '00000000-0000-0000-0000-000000000c01', 'passage', '00000000-0000-0000-0000-000000000402', '00000000-0000-0000-0000-000000000502', '00000000-0000-0000-0000-000000000602', '00000000-0000-0000-0000-000000000702', '00000000-0000-0000-0000-000000000802', 'wrong corpus', 'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', 0, 100, 1
    )
$sql$);
SELECT pg_temp.expect_rejection('cross-fact provenance', $sql$
    INSERT INTO retrieval_items (
        id, index_version_id, kind, entity_id, document_id, document_version_id,
        section_id, source_span_id, financial_fact_id, content, content_sha256,
        start_char, end_char, token_count
    ) VALUES (
        '00000000-0000-0000-0000-000000000d12', '00000000-0000-0000-0000-000000000c01', 'fact', '00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-000000000902', 'wrong fact', 'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee', 0, 100, 1
    )
$sql$);
SELECT pg_temp.expect_rejection('cross-table provenance', $sql$
    INSERT INTO retrieval_items (
        id, index_version_id, kind, entity_id, document_id, document_version_id,
        section_id, source_span_id, table_id, table_row_index, content,
        content_sha256, start_char, end_char, token_count
    ) VALUES (
        '00000000-0000-0000-0000-000000000d13', '00000000-0000-0000-0000-000000000c01', 'table_row', '00000000-0000-0000-0000-000000000401', '00000000-0000-0000-0000-000000000501', '00000000-0000-0000-0000-000000000601', '00000000-0000-0000-0000-000000000701', '00000000-0000-0000-0000-000000000801', '00000000-0000-0000-0000-000000000a02', 0, 'wrong table', 'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 0, 100, 1
    )
$sql$);

INSERT INTO retrieval_embeddings (
    retrieval_item_id, index_version_id, provider, model, dimensions,
    embedding, content_sha256
) VALUES (
    '00000000-0000-0000-0000-000000000d01', '00000000-0000-0000-0000-000000000c01',
    'openai', 'text-embedding-3-small', 512,
    array_fill(0::real, ARRAY[512])::halfvec,
    'sha256:1111111111111111111111111111111111111111111111111111111111111111'
);
SELECT pg_temp.expect_rejection('embedding hash/index/model mismatch', $sql$
    INSERT INTO retrieval_embeddings (
        retrieval_item_id, index_version_id, provider, model, dimensions,
        embedding, content_sha256
    ) VALUES (
        '00000000-0000-0000-0000-000000000d01', '00000000-0000-0000-0000-000000000c02',
        'other', 'wrong', 512, array_fill(0::real, ARRAY[512])::halfvec,
        'sha256:9999999999999999999999999999999999999999999999999999999999999999'
    )
$sql$);

UPDATE retrieval_index_versions
SET status = 'ready', published_at = now()
WHERE id IN ('00000000-0000-0000-0000-000000000c01', '00000000-0000-0000-0000-000000000c02');
SELECT pg_temp.expect_rejection('published index rollback', $sql$
    UPDATE retrieval_index_versions
    SET status = 'draft', published_at = NULL
    WHERE id = '00000000-0000-0000-0000-000000000c01'
$sql$);

INSERT INTO queries (
    id, org_id, workspace_id, created_by, question, effective_as_of,
    corpus_version_id, index_version_id, plan, planner_version
) VALUES
    ('00000000-0000-0000-0000-000000000e01', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000201', 'one?', now(), '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1'),
    ('00000000-0000-0000-0000-000000000e02', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-000000000202', 'two?', now(), '00000000-0000-0000-0000-000000000b02', '00000000-0000-0000-0000-000000000c02', '{}'::jsonb, 'planner-v1');
SELECT pg_temp.expect_rejection('query workspace tenant', $sql$
    INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e11', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-000000000201', 'bad', now(), '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1', '{}'::jsonb, NULL, now())
$sql$);
SELECT pg_temp.expect_rejection('query actor membership', $sql$
    INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e12', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000202', 'bad', now(), '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1', '{}'::jsonb, NULL, now())
$sql$);
SELECT pg_temp.expect_rejection('query parent tenant', $sql$
    INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e13', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000201', 'bad', now(), '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1', '{}'::jsonb, '00000000-0000-0000-0000-000000000e02', now())
$sql$);
SELECT pg_temp.expect_rejection('query corpus/index mismatch', $sql$
    INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e14', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000201', 'bad', now(), '00000000-0000-0000-0000-000000000b02', '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1', '{}'::jsonb, NULL, now())
$sql$);
SELECT pg_temp.expect_rejection('query unpublished index', $sql$
    INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e15', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000201', 'bad', now(), '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000c03', '{}'::jsonb, 'planner-v1', '{}'::jsonb, NULL, now())
$sql$);
SELECT pg_temp.expect_rejection('query exceeds workspace cutoff', $sql$
    INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e17', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000301', '00000000-0000-0000-0000-000000000201', 'future query', now() + interval '1 day', '00000000-0000-0000-0000-000000000b01', '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1', '{}'::jsonb, NULL, now())
$sql$);

INSERT INTO queries (
    id, org_id, workspace_id, created_by, question, effective_as_of,
    corpus_version_id, index_version_id, plan, planner_version
) VALUES (
    '00000000-0000-0000-0000-000000000e16',
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000301',
    '00000000-0000-0000-0000-000000000201',
    'historical query', now() - interval '1 day',
    '00000000-0000-0000-0000-000000000b01',
    '00000000-0000-0000-0000-000000000c01', '{}'::jsonb, 'planner-v1'
);

INSERT INTO retrieval_runs (
    id, org_id, query_id, mode, config_hash, embedding_provider,
    embedding_model, planner_version
) VALUES
    ('00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000e01', 'execute', 'sha256:1111111111111111111111111111111111111111111111111111111111111111', 'openai', 'text-embedding-3-small', 'planner-v1'),
    ('00000000-0000-0000-0000-000000000f02', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000e02', 'execute', 'sha256:2222222222222222222222222222222222222222222222222222222222222222', 'openai', 'text-embedding-3-small', 'planner-v1'),
    ('00000000-0000-0000-0000-000000000f03', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000e01', 'execute', 'sha256:3333333333333333333333333333333333333333333333333333333333333333', 'openai', 'text-embedding-3-small', 'planner-v1');
INSERT INTO retrieval_runs (
    id, org_id, query_id, mode, config_hash, embedding_provider,
    embedding_model, planner_version
) VALUES (
    '00000000-0000-0000-0000-000000000f16',
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000e16', 'execute',
    'sha256:6666666666666666666666666666666666666666666666666666666666666666',
    'openai', 'text-embedding-3-small', 'planner-v1'
);
SELECT pg_temp.expect_rejection('run query tenant', $sql$
    INSERT INTO retrieval_runs (id, org_id, query_id, mode, config_hash, embedding_provider, embedding_model, planner_version)
    VALUES ('00000000-0000-0000-0000-000000000f11', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000e02', 'execute', 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'openai', 'text-embedding-3-small', 'planner-v1')
$sql$);
SELECT pg_temp.expect_rejection('run provider pin', $sql$
    INSERT INTO retrieval_runs (id, org_id, query_id, mode, config_hash, embedding_provider, embedding_model, planner_version)
    VALUES ('00000000-0000-0000-0000-000000000f12', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000e01', 'execute', 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'other', 'wrong', 'planner-v1')
$sql$);
SELECT pg_temp.expect_rejection('run parent tenant', $sql$
    INSERT INTO retrieval_runs (id, org_id, query_id, parent_run_id, mode, config_hash, embedding_provider, embedding_model, planner_version)
    VALUES ('00000000-0000-0000-0000-000000000f13', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000e01', '00000000-0000-0000-0000-000000000f02', 'rerun', 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'openai', 'text-embedding-3-small', 'planner-v1')
$sql$);
SELECT pg_temp.expect_rejection('event run tenant', $sql$
    INSERT INTO retrieval_events VALUES ('00000000-0000-0000-0000-000000000f02', '00000000-0000-0000-0000-000000000101', 99, 'heartbeat', '{}'::jsonb, now())
$sql$);
SELECT pg_temp.expect_rejection('event sequence gap', $sql$
    INSERT INTO retrieval_events VALUES ('00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000101', 2, 'heartbeat', '{}'::jsonb, now())
$sql$);

UPDATE retrieval_runs SET status = 'planning' WHERE id = '00000000-0000-0000-0000-000000000f01';
UPDATE retrieval_runs SET status = 'retrieving' WHERE id = '00000000-0000-0000-0000-000000000f01';
INSERT INTO retrieval_candidates (
    id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank,
    raw_score, normalized_score, rrf_contribution, fused_score, rerank_score,
    fused_rank, accepted, timing_ms
) VALUES
    ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d01', 'dense', 0, 1, '0.9', '0.9', '0.016', '0.016', NULL, 1, true, 1),
    ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000f02', '00000000-0000-0000-0000-000000000d02', 'dense', 0, 1, '0.8', '0.8', '0.016', '0.016', NULL, 1, true, 1);
SELECT pg_temp.expect_rejection('candidate run/item index mismatch', $sql$
    INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, accepted, timing_ms)
    VALUES ('10000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d02', 'lexical', 0, 1, '1', '0.01', '0.01', false, 1)
$sql$);
SELECT pg_temp.expect_rejection('candidate decimal string', $sql$
    INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, accepted, timing_ms)
    VALUES ('10000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d03', 'facts', 0, 1, 'NaN', '0.01', '0.01', false, 1)
$sql$);
SELECT pg_temp.expect_rejection('candidate run tenant', $sql$
    INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, accepted, timing_ms)
    VALUES ('10000000-0000-0000-0000-000000000014', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f02', '00000000-0000-0000-0000-000000000d02', 'dense', 0, 2, '1', '0.01', '0.01', false, 1)
$sql$);
SELECT pg_temp.expect_rejection('candidate published after query cutoff', $sql$
    INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, accepted, timing_ms)
    VALUES ('10000000-0000-0000-0000-000000000016', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f16', '00000000-0000-0000-0000-000000000d01', 'dense', 0, 1, '1', '0.01', '0.01', false, 1)
$sql$);

INSERT INTO claims (id, org_id, run_id, ord, text, status, confidence)
VALUES
    ('20000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', 0, 'claim', 'supported', '1'),
    ('20000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000f02', 0, 'claim 2', 'supported', '1');
SELECT pg_temp.expect_rejection('claim run tenant', $sql$
    INSERT INTO claims VALUES ('20000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f02', 1, 'bad', 'unsupported', NULL, '{}'::jsonb, now())
$sql$);
INSERT INTO citations (
    id, org_id, run_id, claim_id, retrieval_item_id, source_span_id, status
) VALUES (
    '30000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '20000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000d01', '00000000-0000-0000-0000-000000000801', 'entailed'
);
SELECT pg_temp.expect_rejection('citation item/span mismatch', $sql$
    INSERT INTO citations VALUES ('30000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '20000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000d01', '00000000-0000-0000-0000-000000000802', 'entailed', NULL, NULL, NULL, '{}'::jsonb, NULL, now())
$sql$);
SELECT pg_temp.expect_rejection('citation claim/run tenant', $sql$
    INSERT INTO citations VALUES ('30000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '20000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000d01', '00000000-0000-0000-0000-000000000801', 'entailed', NULL, NULL, NULL, '{}'::jsonb, NULL, now())
$sql$);

INSERT INTO retrieval_feedback (
    id, org_id, run_id, retrieval_item_id, label, actor_user_id
) VALUES
    ('40000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d01', 'relevant', '00000000-0000-0000-0000-000000000201'),
    ('40000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000f02', '00000000-0000-0000-0000-000000000d02', 'relevant', '00000000-0000-0000-0000-000000000202');
INSERT INTO retrieval_feedback (
    id, org_id, run_id, retrieval_item_id, label, actor_user_id,
    supersedes_feedback_id
) VALUES (
    '40000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d01', 'irrelevant', '00000000-0000-0000-0000-000000000201', '40000000-0000-0000-0000-000000000001'
);
SELECT pg_temp.expect_rejection('feedback supersession run/org mismatch', $sql$
    INSERT INTO retrieval_feedback (id, org_id, run_id, retrieval_item_id, label, actor_user_id, supersedes_feedback_id)
    VALUES ('40000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d01', 'irrelevant', '00000000-0000-0000-0000-000000000201', '40000000-0000-0000-0000-000000000002')
$sql$);
SELECT pg_temp.expect_rejection('feedback actor membership', $sql$
    INSERT INTO retrieval_feedback (id, org_id, run_id, retrieval_item_id, label, actor_user_id)
    VALUES ('40000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d01', 'irrelevant', '00000000-0000-0000-0000-000000000202')
$sql$);

UPDATE retrieval_runs SET status = 'fusing' WHERE id = '00000000-0000-0000-0000-000000000f01';
UPDATE retrieval_runs SET status = 'generating' WHERE id = '00000000-0000-0000-0000-000000000f01';
UPDATE retrieval_runs SET status = 'verifying' WHERE id = '00000000-0000-0000-0000-000000000f01';
INSERT INTO retrieval_events (run_id, org_id, seq, event_type)
VALUES ('00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000101', 1, 'run_completed');
UPDATE retrieval_runs SET status = 'succeeded', finished_at = now()
WHERE id = '00000000-0000-0000-0000-000000000f01';
SELECT pg_temp.expect_rejection('event after terminal', $sql$
    INSERT INTO retrieval_events VALUES ('00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000101', 2, 'heartbeat', '{}'::jsonb, now())
$sql$);
SELECT pg_temp.expect_rejection('candidate after terminal', $sql$
    INSERT INTO retrieval_candidates (id, org_id, run_id, retrieval_item_id, lane, variant_index, lane_rank, raw_score, rrf_contribution, fused_score, accepted, timing_ms)
    VALUES ('10000000-0000-0000-0000-000000000013', '00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000f01', '00000000-0000-0000-0000-000000000d03', 'facts', 0, 1, '1', '0.01', '0.01', false, 1)
$sql$);
SELECT pg_temp.expect_rejection('terminal run mutation', $sql$
    UPDATE retrieval_runs SET cost_usd = 1 WHERE id = '00000000-0000-0000-0000-000000000f01'
$sql$);

INSERT INTO retrieval_events (run_id, org_id, seq, event_type)
VALUES ('00000000-0000-0000-0000-000000000f03', '00000000-0000-0000-0000-000000000101', 1, 'run_cancelled');
UPDATE retrieval_runs SET status = 'cancelled', finished_at = now()
WHERE id = '00000000-0000-0000-0000-000000000f03';

INSERT INTO retrieval_events (run_id, org_id, seq, event_type)
VALUES ('00000000-0000-0000-0000-000000000f02', '00000000-0000-0000-0000-000000000102', 1, 'run_failed');
SELECT pg_temp.expect_rejection('terminal status/event mismatch', $sql$
    UPDATE retrieval_runs SET status = 'cancelled', finished_at = now()
    WHERE id = '00000000-0000-0000-0000-000000000f02'
$sql$);

SET LOCAL ROLE fel_app;
SELECT set_config(
    'request.jwt.claims',
    '{"org_id":"00000000-0000-0000-0000-000000000101"}',
    true
);
DO $$
BEGIN
    IF (SELECT count(*) FROM queries WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0
       OR (SELECT count(*) FROM retrieval_runs WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0
       OR (SELECT count(*) FROM retrieval_feedback WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0
       OR (SELECT count(*) FROM citations WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0 THEN
        RAISE EXCEPTION 'cross-organization rows are visible to fel_app';
    END IF;
END
$$;
SELECT pg_temp.expect_rejection(
    'RLS rejects cross-organization query insert',
    $sql$
        INSERT INTO queries VALUES ('00000000-0000-0000-0000-000000000e18', '00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000302', '00000000-0000-0000-0000-000000000202', 'RLS bad', now(), '00000000-0000-0000-0000-000000000b02', '00000000-0000-0000-0000-000000000c02', '{}'::jsonb, 'planner-v1', '{}'::jsonb, NULL, now())
    $sql$,
    ARRAY['42501']
);
RESET ROLE;

DO $$
BEGIN
    RAISE NOTICE 'ok - all retrieval migration regression cases passed';
END
$$;
ROLLBACK;
