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

-- Minimal seed chain for a queries insert (org -> membership -> workspace,
-- corpus version -> index version). Distinct 0x000d/0x000e id block to stay
-- clear of the 0003 harness ids.
INSERT INTO organizations (id, name) VALUES
    ('00000000-0000-0000-0000-00000000d101', 'Guard Fix Org');
INSERT INTO memberships (org_id, user_id, role) VALUES
    ('00000000-0000-0000-0000-00000000d101', '00000000-0000-0000-0000-00000000d201', 'owner');
INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, fiscal_calendar, as_of) VALUES
    ('00000000-0000-0000-0000-00000000d301', '00000000-0000-0000-0000-00000000d101', 'Guard WS',
     '00000000-0000-0000-0000-00000000d401', 'USD', 'calendar', '2027-01-01T00:00:00Z');
INSERT INTO corpus_versions (id, label, status, is_active, published_at) VALUES
    ('00000000-0000-0000-0000-00000000d501', 'Guard Corpus', 'superseded', false, now());
INSERT INTO retrieval_index_versions (
    id, corpus_version_id, chunker_version, config_hash,
    embedding_provider, embedding_model
) VALUES
    ('00000000-0000-0000-0000-00000000d601', '00000000-0000-0000-0000-00000000d501', 'v1',
     'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
     'mock', 'mock-512'),
    ('00000000-0000-0000-0000-00000000d602', '00000000-0000-0000-0000-00000000d501', 'v2',
     'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
     'mock', 'mock-512');
-- d601 becomes published (building -> ready); d602 stays building (unpublished).
UPDATE retrieval_index_versions SET status = 'building'
    WHERE id = '00000000-0000-0000-0000-00000000d601';
UPDATE retrieval_index_versions SET status = 'ready', published_at = now()
    WHERE id = '00000000-0000-0000-0000-00000000d601';
UPDATE retrieval_index_versions SET status = 'building'
    WHERE id = '00000000-0000-0000-0000-00000000d602';

-- THE regression: the application role must be able to create a query
-- against a published index. Before 0005 this raised 42501 (FOR SHARE on a
-- SELECT-only table); a rejection of any kind here fails the harness.
SET LOCAL ROLE fel_app;
SELECT set_config(
    'request.jwt.claims',
    '{"org_id":"00000000-0000-0000-0000-00000000d101"}',
    true
);
INSERT INTO queries (
    id, org_id, workspace_id, created_by, question, effective_as_of,
    corpus_version_id, index_version_id, plan, planner_version
) VALUES (
    '00000000-0000-0000-0000-00000000d701',
    '00000000-0000-0000-0000-00000000d101',
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d201',
    'guard fix regression query',
    '2026-01-01T00:00:00Z',
    '00000000-0000-0000-0000-00000000d501',
    '00000000-0000-0000-0000-00000000d601',
    '{}'::jsonb,
    'planner-v1'
);
DO $$
BEGIN
    IF (SELECT count(*) FROM queries
        WHERE id = '00000000-0000-0000-0000-00000000d701') <> 1 THEN
        RAISE EXCEPTION 'not ok - fel_app query insert did not persist';
    END IF;
    RAISE NOTICE 'ok - fel_app can create a query against a published index';
END
$$;

-- Guard logic must remain intact under fel_app: unpublished pin rejected.
SELECT pg_temp.expect_rejection(
    'fel_app query pinning an unpublished index',
    $sql$
        INSERT INTO queries (
            id, org_id, workspace_id, created_by, question, effective_as_of,
            corpus_version_id, index_version_id, plan, planner_version
        ) VALUES (
            '00000000-0000-0000-0000-00000000d702',
            '00000000-0000-0000-0000-00000000d101',
            '00000000-0000-0000-0000-00000000d301',
            '00000000-0000-0000-0000-00000000d201',
            'unpublished pin must fail',
            '2026-01-01T00:00:00Z',
            '00000000-0000-0000-0000-00000000d501',
            '00000000-0000-0000-0000-00000000d602',
            '{}'::jsonb,
            'planner-v1'
        )
    $sql$,
    ARRAY['P0001']
);

-- Cutoff rule also intact under fel_app.
SELECT pg_temp.expect_rejection(
    'fel_app query cutoff beyond workspace cutoff',
    $sql$
        INSERT INTO queries (
            id, org_id, workspace_id, created_by, question, effective_as_of,
            corpus_version_id, index_version_id, plan, planner_version
        ) VALUES (
            '00000000-0000-0000-0000-00000000d703',
            '00000000-0000-0000-0000-00000000d101',
            '00000000-0000-0000-0000-00000000d301',
            '00000000-0000-0000-0000-00000000d201',
            'cutoff beyond workspace must fail',
            '2028-01-01T00:00:00Z',
            '00000000-0000-0000-0000-00000000d501',
            '00000000-0000-0000-0000-00000000d601',
            '{}'::jsonb,
            'planner-v1'
        )
    $sql$,
    ARRAY['P0001']
);
RESET ROLE;

-- Immutability unchanged (superuser sanity).
SELECT pg_temp.expect_rejection(
    'query mutation after insert',
    $sql$
        UPDATE queries SET question = 'rewritten'
        WHERE id = '00000000-0000-0000-0000-00000000d701'
    $sql$,
    ARRAY['P0001']
);

DO $$ BEGIN RAISE NOTICE 'ok - all 0005 query-guard regression cases passed'; END $$;

ROLLBACK;
