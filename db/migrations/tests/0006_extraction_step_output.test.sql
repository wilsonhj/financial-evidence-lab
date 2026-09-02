-- Harness for 0006: extraction_run_steps.output + the NULL-confidence
-- relaxation (ADR-0011 / issues #157, #194).
--
-- Everything that fel_app is granted is exercised UNDER fel_app with
-- request.jwt.claims set, per the convention in db/migrations/README.md:
-- superuser-only coverage cannot catch privilege or lock bugs, and this
-- migration's whole claim about grants is that 0004's TABLE-level grant already
-- covers the new column.
--
-- Distinct 0x000f id block, clear of the 0004 (0x0001/0x0002) and 0005
-- (0x000d) harness ids.

\set ON_ERROR_STOP on

BEGIN;

\ir _helpers.sql

INSERT INTO organizations (id, name) VALUES
    ('00000000-0000-0000-0000-00000000f101', 'Step Output Org'),
    ('00000000-0000-0000-0000-00000000f102', 'Step Output Other Org');
INSERT INTO memberships (org_id, user_id, role) VALUES
    ('00000000-0000-0000-0000-00000000f101', '00000000-0000-0000-0000-00000000f201', 'owner'),
    ('00000000-0000-0000-0000-00000000f102', '00000000-0000-0000-0000-00000000f202', 'owner');
INSERT INTO workspaces (id, org_id, name, entity_id, base_currency, fiscal_calendar, as_of) VALUES
    ('00000000-0000-0000-0000-00000000f301', '00000000-0000-0000-0000-00000000f101', 'Step WS',
     '00000000-0000-0000-0000-00000000f401', 'USD', 'calendar', now()),
    ('00000000-0000-0000-0000-00000000f302', '00000000-0000-0000-0000-00000000f102', 'Other WS',
     '00000000-0000-0000-0000-00000000f402', 'USD', 'calendar', now());
INSERT INTO corpus_versions (id, label, status, is_active, published_at) VALUES
    ('00000000-0000-0000-0000-00000000fb01', 'Step Output Corpus', 'active', true, now());
INSERT INTO extraction_policies (id, org_id, version, created_by) VALUES
    ('50000000-0000-0000-0000-00000000f001', '00000000-0000-0000-0000-00000000f101', 1,
     '00000000-0000-0000-0000-00000000f201'),
    ('50000000-0000-0000-0000-00000000f002', '00000000-0000-0000-0000-00000000f102', 1,
     '00000000-0000-0000-0000-00000000f202');

-- f001 stays open for the whole harness; f002 is driven terminal; f003 belongs
-- to the OTHER org and exists only to be invisible.
INSERT INTO extraction_runs (
    id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
    ontology_version, workflow_version, provider, model, policy_id,
    input_hash, idempotency_key, created_by
) VALUES
    (
        '60000000-0000-0000-0000-00000000f001',
        '00000000-0000-0000-0000-00000000f101',
        '00000000-0000-0000-0000-00000000f301',
        '00000000-0000-0000-0000-00000000f401',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-00000000fb01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-00000000f001',
        'sha256:1111111111111111111111111111111111111111111111111111111111111111',
        'idem-0006-open', '00000000-0000-0000-0000-00000000f201'
    ),
    (
        '60000000-0000-0000-0000-00000000f002',
        '00000000-0000-0000-0000-00000000f101',
        '00000000-0000-0000-0000-00000000f301',
        '00000000-0000-0000-0000-00000000f401',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-00000000fb01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-00000000f001',
        'sha256:2222222222222222222222222222222222222222222222222222222222222222',
        'idem-0006-terminal', '00000000-0000-0000-0000-00000000f201'
    ),
    (
        '60000000-0000-0000-0000-00000000f003',
        '00000000-0000-0000-0000-00000000f102',
        '00000000-0000-0000-0000-00000000f302',
        '00000000-0000-0000-0000-00000000f402',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-00000000fb01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-00000000f002',
        'sha256:3333333333333333333333333333333333333333333333333333333333333333',
        'idem-0006-other-org', '00000000-0000-0000-0000-00000000f202'
    );
UPDATE extraction_runs SET status = 'running', started_at = now()
    WHERE id IN ('60000000-0000-0000-0000-00000000f001',
                 '60000000-0000-0000-0000-00000000f002',
                 '60000000-0000-0000-0000-00000000f003');

-- Other org's step row: seeded as the superuser so the cross-org read below has
-- something it could have leaked.
INSERT INTO extraction_run_steps (
    id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
    output, workflow_version, schema_version, prompt_version
) VALUES (
    '70000000-0000-0000-0000-00000000f0f1',
    '00000000-0000-0000-0000-00000000f102',
    '60000000-0000-0000-0000-00000000f003',
    'classify', 1, 'succeeded',
    'sha256:9999999999999999999999999999999999999999999999999999999999999999',
    'sha256:8888888888888888888888888888888888888888888888888888888888888888',
    '{"document_type":"10-Q"}'::jsonb,
    'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
);

SET LOCAL ROLE fel_app;
SELECT set_config(
    'request.jwt.claims',
    '{"org_id":"00000000-0000-0000-0000-00000000f101"}',
    true
);

-- ---------------------------------------------------------------------------
-- 1. A succeeded step carrying its output survives, written by fel_app.
-- ---------------------------------------------------------------------------
INSERT INTO extraction_run_steps (
    id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
    output, workflow_version, schema_version, prompt_version
) VALUES (
    '70000000-0000-0000-0000-00000000f001',
    '00000000-0000-0000-0000-00000000f101',
    '60000000-0000-0000-0000-00000000f001',
    'assemble_evidence', 1, 'succeeded',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    '[{"source_span_id":"00000000-0000-0000-0000-00000000f801","text":"ARR was $100 million."}]'::jsonb,
    'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
);
DO $$
BEGIN
    IF (SELECT output -> 0 ->> 'text' FROM extraction_run_steps
        WHERE id = '70000000-0000-0000-0000-00000000f001')
       IS DISTINCT FROM 'ARR was $100 million.' THEN
        RAISE EXCEPTION 'not ok - fel_app step output did not round-trip';
    END IF;
    RAISE NOTICE 'ok - fel_app writes and reads extraction_run_steps.output';
END
$$;

-- ---------------------------------------------------------------------------
-- 2. output and output_hash are both null or both set.
-- ---------------------------------------------------------------------------
SELECT pg_temp.expect_rejection('output without output_hash', $sql$
    INSERT INTO extraction_run_steps (
        id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
        output, workflow_version, schema_version, prompt_version
    ) VALUES (
        '70000000-0000-0000-0000-00000000f002',
        '00000000-0000-0000-0000-00000000f101',
        '60000000-0000-0000-0000-00000000f001',
        'classify', 1, 'succeeded',
        'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
        NULL,
        '{"document_type":"10-Q"}'::jsonb,
        'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
    )
$sql$, ARRAY['23514']);

SELECT pg_temp.expect_rejection('output_hash without output', $sql$
    INSERT INTO extraction_run_steps (
        id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
        output, workflow_version, schema_version, prompt_version
    ) VALUES (
        '70000000-0000-0000-0000-00000000f003',
        '00000000-0000-0000-0000-00000000f101',
        '60000000-0000-0000-0000-00000000f001',
        'classify', 2, 'succeeded',
        'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
        'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
        NULL,
        'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
    )
$sql$, ARRAY['23514']);

-- Neither set is legal: a skipped or failed step produces no output at all.
INSERT INTO extraction_run_steps (
    id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
    output, workflow_version, schema_version, prompt_version
) VALUES (
    '70000000-0000-0000-0000-00000000f004',
    '00000000-0000-0000-0000-00000000f101',
    '60000000-0000-0000-0000-00000000f001',
    'extract_guidance', 1, 'skipped',
    'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
    NULL, NULL,
    'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
);

-- ---------------------------------------------------------------------------
-- 3. output may advance within an OPEN run; identity pins still may not.
-- ---------------------------------------------------------------------------
UPDATE extraction_run_steps
SET output = '[{"source_span_id":"00000000-0000-0000-0000-00000000f801","text":"ARR was $101 million."}]'::jsonb,
    output_hash = 'sha256:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd'
WHERE id = '70000000-0000-0000-0000-00000000f001';
DO $$
BEGIN
    IF (SELECT output -> 0 ->> 'text' FROM extraction_run_steps
        WHERE id = '70000000-0000-0000-0000-00000000f001')
       IS DISTINCT FROM 'ARR was $101 million.' THEN
        RAISE EXCEPTION 'not ok - output update on an open run did not apply';
    END IF;
    RAISE NOTICE 'ok - output advances within an open run';
END
$$;

SELECT pg_temp.expect_rejection('step identity pin update', $sql$
    UPDATE extraction_run_steps SET input_hash =
        'sha256:0000000000000000000000000000000000000000000000000000000000000000'
    WHERE id = '70000000-0000-0000-0000-00000000f001'
$sql$, ARRAY['P0001']);

-- The pair CHECK binds UPDATEs too: output cannot be cleared out from under a
-- hash that still describes it.
SELECT pg_temp.expect_rejection('clearing output while output_hash remains', $sql$
    UPDATE extraction_run_steps SET output = NULL
    WHERE id = '70000000-0000-0000-0000-00000000f001'
$sql$, ARRAY['23514']);

-- ---------------------------------------------------------------------------
-- 4. Cross-org rows stay invisible (RLS is column-agnostic; the new column
--    does not open a read path).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF (SELECT count(*) FROM extraction_run_steps
        WHERE org_id = '00000000-0000-0000-0000-00000000f102') <> 0 THEN
        RAISE EXCEPTION 'not ok - cross-organization step rows are visible to fel_app';
    END IF;
    RAISE NOTICE 'ok - cross-organization step output is not readable';
END
$$;

-- ---------------------------------------------------------------------------
-- 5. Issue #194: an unscored proposal persists NULL confidence.
-- ---------------------------------------------------------------------------
INSERT INTO extraction_proposals (
    id, org_id, workspace_id, run_id, kind, metric_id, payload,
    raw_payload_hash, definition_hash, record_confidence, review_priority
) VALUES (
    '80000000-0000-0000-0000-00000000f001',
    '00000000-0000-0000-0000-00000000f101',
    '00000000-0000-0000-0000-00000000f301',
    '60000000-0000-0000-0000-00000000f001',
    'kpi', 'arr', '{"kind":"kpi"}'::jsonb,
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    NULL, 'normal'
);
DO $$
BEGIN
    IF (SELECT record_confidence IS NULL FROM extraction_proposals
        WHERE id = '80000000-0000-0000-0000-00000000f001') IS NOT TRUE THEN
        RAISE EXCEPTION 'not ok - unscored proposal did not persist NULL confidence';
    END IF;
    RAISE NOTICE 'ok - unscored proposals persist NULL record_confidence';
END
$$;

-- The range CHECK still binds every value that IS supplied.
SELECT pg_temp.expect_rejection('out-of-range record_confidence', $sql$
    INSERT INTO extraction_proposals (
        id, org_id, workspace_id, run_id, kind, metric_id, payload,
        raw_payload_hash, definition_hash, record_confidence
    ) VALUES (
        '80000000-0000-0000-0000-00000000f002',
        '00000000-0000-0000-0000-00000000f101',
        '00000000-0000-0000-0000-00000000f301',
        '60000000-0000-0000-0000-00000000f001',
        'kpi', 'arr', '{"kind":"kpi"}'::jsonb,
        'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
        'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
        1.500
    )
$sql$, ARRAY['23514']);

RESET ROLE;

-- ---------------------------------------------------------------------------
-- 6. The terminal-run guard is UNCHANGED: no late step insert, no late update,
--    and the new column does not create a way around either.
-- ---------------------------------------------------------------------------
INSERT INTO extraction_run_steps (
    id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
    output, workflow_version, schema_version, prompt_version
) VALUES (
    '70000000-0000-0000-0000-00000000f011',
    '00000000-0000-0000-0000-00000000f101',
    '60000000-0000-0000-0000-00000000f002',
    'classify', 1, 'succeeded',
    'sha256:1212121212121212121212121212121212121212121212121212121212121212',
    'sha256:3434343434343434343434343434343434343434343434343434343434343434',
    '{"document_type":"10-K"}'::jsonb,
    'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
);
UPDATE extraction_runs SET status = 'succeeded', finished_at = now()
    WHERE id = '60000000-0000-0000-0000-00000000f002';

SELECT pg_temp.expect_rejection('late step insert on a terminal run', $sql$
    INSERT INTO extraction_run_steps (
        id, org_id, run_id, step_name, attempt, status, input_hash, output_hash,
        output, workflow_version, schema_version, prompt_version
    ) VALUES (
        '70000000-0000-0000-0000-00000000f012',
        '00000000-0000-0000-0000-00000000f101',
        '60000000-0000-0000-0000-00000000f002',
        'normalize', 1, 'succeeded',
        'sha256:5656565656565656565656565656565656565656565656565656565656565656',
        'sha256:7878787878787878787878787878787878787878787878787878787878787878',
        '{"normalized":[]}'::jsonb,
        'workflow-v1', 'extraction-payload/v1', 'prompts/v1'
    )
$sql$, ARRAY['P0001']);

SELECT pg_temp.expect_rejection('late output rewrite on a terminal run', $sql$
    UPDATE extraction_run_steps
    SET output = '{"document_type":"tampered"}'::jsonb,
        output_hash = 'sha256:9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a'
    WHERE id = '70000000-0000-0000-0000-00000000f011'
$sql$, ARRAY['P0001']);

SELECT pg_temp.expect_rejection('step delete', $sql$
    DELETE FROM extraction_run_steps
    WHERE id = '70000000-0000-0000-0000-00000000f011'
$sql$, ARRAY['P0001']);

DO $$ BEGIN RAISE NOTICE 'ok - all 0006 step-output cases passed'; END $$;

ROLLBACK;
