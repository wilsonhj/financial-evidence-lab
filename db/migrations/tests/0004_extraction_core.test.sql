\set ON_ERROR_STOP on

BEGIN;

CREATE FUNCTION pg_temp.expect_rejection(
    test_name text,
    statement text,
    expected_states text[] DEFAULT ARRAY['23503', '23514', 'P0001', '23505']
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
INSERT INTO corpus_versions (id, label, status, is_active, published_at) VALUES
    ('00000000-0000-0000-0000-000000000b01', 'Corpus 1', 'active', true, now()),
    ('00000000-0000-0000-0000-000000000b02', 'Corpus 2', 'superseded', false, now());

INSERT INTO extraction_policies (
    id, org_id, version, created_by
) VALUES
    ('50000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 1, '00000000-0000-0000-0000-000000000201'),
    ('50000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000102', 1, '00000000-0000-0000-0000-000000000202');
SELECT pg_temp.expect_rejection('policy immutability', $sql$
    UPDATE extraction_policies SET max_calls = 5
    WHERE id = '50000000-0000-0000-0000-000000000001'
$sql$);
SELECT pg_temp.expect_rejection('policy tenant membership', $sql$
    INSERT INTO extraction_policies (id, org_id, version, created_by)
    VALUES ('50000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000101', 2, '00000000-0000-0000-0000-000000000202')
$sql$);

INSERT INTO extraction_runs (
    id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
    ontology_version, workflow_version, provider, model, policy_id,
    input_hash, idempotency_key, created_by
) VALUES
    (
        '60000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000301',
        '00000000-0000-0000-0000-000000000401',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-000000000b01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000001',
        'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        'idem-run-1', '00000000-0000-0000-0000-000000000201'
    ),
    (
        '60000000-0000-0000-0000-000000000002',
        '00000000-0000-0000-0000-000000000102',
        '00000000-0000-0000-0000-000000000302',
        '00000000-0000-0000-0000-000000000402',
        ARRAY['guidance']::text[], now(),
        '00000000-0000-0000-0000-000000000b02',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000002',
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'idem-run-2', '00000000-0000-0000-0000-000000000202'
    ),
    (
        '60000000-0000-0000-0000-000000000003',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000301',
        '00000000-0000-0000-0000-000000000401',
        ARRAY['kpi', 'guidance']::text[], now(),
        '00000000-0000-0000-0000-000000000b01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000001',
        'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
        'idem-run-3', '00000000-0000-0000-0000-000000000201'
    );

SELECT pg_temp.expect_rejection('run idempotency', $sql$
    INSERT INTO extraction_runs (
        id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
        ontology_version, workflow_version, provider, model, policy_id,
        input_hash, idempotency_key, created_by
    ) VALUES (
        '60000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000301',
        '00000000-0000-0000-0000-000000000401',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-000000000b01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000001',
        'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
        'idem-run-1', '00000000-0000-0000-0000-000000000201'
    )
$sql$);
SELECT pg_temp.expect_rejection('run workspace tenant', $sql$
    INSERT INTO extraction_runs (
        id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
        ontology_version, workflow_version, provider, model, policy_id,
        input_hash, idempotency_key, created_by
    ) VALUES (
        '60000000-0000-0000-0000-000000000012',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000302',
        '00000000-0000-0000-0000-000000000401',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-000000000b01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000001',
        'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
        'idem-run-bad-ws', '00000000-0000-0000-0000-000000000201'
    )
$sql$);
SELECT pg_temp.expect_rejection('run invalid mode', $sql$
    INSERT INTO extraction_runs (
        id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
        ontology_version, workflow_version, provider, model, policy_id,
        input_hash, idempotency_key, created_by
    ) VALUES (
        '60000000-0000-0000-0000-000000000013',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000301',
        '00000000-0000-0000-0000-000000000401',
        ARRAY['not_a_mode']::text[], now(),
        '00000000-0000-0000-0000-000000000b01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000001',
        'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
        'idem-run-bad-mode', '00000000-0000-0000-0000-000000000201'
    )
$sql$);
SELECT pg_temp.expect_rejection('run policy tenant', $sql$
    INSERT INTO extraction_runs (
        id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
        ontology_version, workflow_version, provider, model, policy_id,
        input_hash, idempotency_key, created_by
    ) VALUES (
        '60000000-0000-0000-0000-000000000014',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000301',
        '00000000-0000-0000-0000-000000000401',
        ARRAY['kpi']::text[], now(),
        '00000000-0000-0000-0000-000000000b01',
        'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
        '50000000-0000-0000-0000-000000000002',
        'sha256:1111111111111111111111111111111111111111111111111111111111111111',
        'idem-run-bad-policy', '00000000-0000-0000-0000-000000000201'
    )
$sql$);

UPDATE extraction_runs SET status = 'running', started_at = now()
WHERE id = '60000000-0000-0000-0000-000000000001';
SELECT pg_temp.expect_rejection('illegal run transition', $sql$
    UPDATE extraction_runs SET status = 'succeeded', finished_at = now()
    WHERE id = '60000000-0000-0000-0000-000000000003'
$sql$);

INSERT INTO extraction_run_steps (
    id, org_id, run_id, step_name, attempt, status, input_hash,
    workflow_version, schema_version, prompt_version
) VALUES (
    '70000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    '60000000-0000-0000-0000-000000000001',
    'kpi_extractor', 1, 'succeeded',
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'workflow-v1', 'extraction-payload/v1', 'prompt-v1'
);
SELECT pg_temp.expect_rejection('step success idempotency', $sql$
    INSERT INTO extraction_run_steps (
        id, org_id, run_id, step_name, attempt, status, input_hash,
        workflow_version, schema_version, prompt_version
    ) VALUES (
        '70000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000101',
        '60000000-0000-0000-0000-000000000001',
        'kpi_extractor', 2, 'succeeded',
        'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        'workflow-v1', 'extraction-payload/v1', 'prompt-v1'
    )
$sql$);
SELECT pg_temp.expect_rejection('step run tenant', $sql$
    INSERT INTO extraction_run_steps (
        id, org_id, run_id, step_name, attempt, status, input_hash,
        workflow_version, schema_version, prompt_version
    ) VALUES (
        '70000000-0000-0000-0000-000000000012',
        '00000000-0000-0000-0000-000000000101',
        '60000000-0000-0000-0000-000000000002',
        'kpi_extractor', 1, 'pending',
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'workflow-v1', 'extraction-payload/v1', 'prompt-v1'
    )
$sql$);
-- G3: demoting a succeeded step (run still open) frees the success-uniqueness
-- index; the step guard freezes 'succeeded' and rejects the transition.
SELECT pg_temp.expect_rejection('step demote from succeeded', $sql$
    UPDATE extraction_run_steps SET status = 'failed'
    WHERE id = '70000000-0000-0000-0000-000000000001'
$sql$, ARRAY['P0001']);

INSERT INTO extraction_run_events (org_id, run_id, event_type, payload)
VALUES (
    '00000000-0000-0000-0000-000000000101',
    '60000000-0000-0000-0000-000000000001',
    'run_started', '{}'::jsonb
);
SELECT pg_temp.expect_rejection('event run tenant', $sql$
    INSERT INTO extraction_run_events (org_id, run_id, event_type)
    VALUES (
        '00000000-0000-0000-0000-000000000101',
        '60000000-0000-0000-0000-000000000002',
        'heartbeat'
    )
$sql$);
SELECT pg_temp.expect_rejection('event append-only update', $sql$
    UPDATE extraction_run_events SET event_type = 'heartbeat'
    WHERE run_id = '60000000-0000-0000-0000-000000000001'
$sql$);

INSERT INTO extraction_proposals (
    id, org_id, workspace_id, run_id, kind, metric_id, payload,
    raw_payload_hash, definition_hash, record_confidence
) VALUES (
    '80000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000301',
    '60000000-0000-0000-0000-000000000001',
    'kpi', 'arr', '{"kind":"kpi"}'::jsonb,
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    0.900
);
SELECT pg_temp.expect_rejection('proposal payload immutability', $sql$
    UPDATE extraction_proposals
    SET payload = '{"kind":"mutated"}'::jsonb
    WHERE id = '80000000-0000-0000-0000-000000000001'
$sql$);
UPDATE extraction_proposals
SET state = 'needs_review', version = 2
WHERE id = '80000000-0000-0000-0000-000000000001';

INSERT INTO extraction_proposal_evidence (
    org_id, proposal_id, source_span_id, document_version_id, role, citation_status
) VALUES (
    '00000000-0000-0000-0000-000000000101',
    '80000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000801',
    '00000000-0000-0000-0000-000000000601',
    'supports', 'verified'
);
SELECT pg_temp.expect_rejection('evidence span/version mismatch', $sql$
    INSERT INTO extraction_proposal_evidence (
        org_id, proposal_id, source_span_id, document_version_id, role, citation_status
    ) VALUES (
        '00000000-0000-0000-0000-000000000101',
        '80000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000801',
        '00000000-0000-0000-0000-000000000602',
        'definition', 'partial'
    )
$sql$);

INSERT INTO extraction_conflicts (
    id, org_id, workspace_id, conflict_key
) VALUES (
    'd0000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000301',
    'arr:2024Q4'
);
-- Resolution lifecycle updates are allowed.
UPDATE extraction_conflicts
SET status = 'resolved',
    resolved_by = '00000000-0000-0000-0000-000000000201',
    resolved_at = now(),
    resolution_note = 'merged'
WHERE id = 'd0000000-0000-0000-0000-000000000001';
-- G1: rewriting a conflict's identity/provenance is rejected by the guard.
SELECT pg_temp.expect_rejection('conflict identity rewrite', $sql$
    UPDATE extraction_conflicts SET conflict_key = 'arr:2025Q1'
    WHERE id = 'd0000000-0000-0000-0000-000000000001'
$sql$, ARRAY['P0001']);

INSERT INTO extraction_reviews (
    id, org_id, workspace_id, action, actor_user_id, reason, idempotency_key,
    expected_versions, input_ids, result_ids
) VALUES (
    '90000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000301',
    'accept', '00000000-0000-0000-0000-000000000201', 'ok',
    'idem-review-1',
    '{"80000000-0000-0000-0000-000000000001": 2}'::jsonb,
    ARRAY['80000000-0000-0000-0000-000000000001']::uuid[],
    ARRAY['a0000000-0000-0000-0000-000000000001']::uuid[]
);
SELECT pg_temp.expect_rejection('review idempotency', $sql$
    INSERT INTO extraction_reviews (
        id, org_id, workspace_id, action, actor_user_id, reason, idempotency_key,
        expected_versions, input_ids
    ) VALUES (
        '90000000-0000-0000-0000-000000000011',
        '00000000-0000-0000-0000-000000000101',
        '00000000-0000-0000-0000-000000000301',
        'accept', '00000000-0000-0000-0000-000000000201', 'dup',
        'idem-review-1',
        '{"80000000-0000-0000-0000-000000000001": 2}'::jsonb,
        ARRAY['80000000-0000-0000-0000-000000000001']::uuid[]
    )
$sql$);
SELECT pg_temp.expect_rejection('review append-only', $sql$
    UPDATE extraction_reviews SET reason = 'mutated'
    WHERE id = '90000000-0000-0000-0000-000000000001'
$sql$);

INSERT INTO approved_extraction_records (
    id, org_id, workspace_id, kind, metric_id, entity_id, version
) VALUES (
    'a0000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000301',
    'kpi', 'arr', '00000000-0000-0000-0000-000000000401', 0
);
INSERT INTO approved_extraction_versions (
    id, org_id, record_id, version, origin_proposal_id, payload,
    evidence_manifest, evidence_manifest_hash, ontology_version,
    normalizer_version, validator_version, approved_by, approval_reason
) VALUES (
    'b0000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'a0000000-0000-0000-0000-000000000001',
    1, '80000000-0000-0000-0000-000000000001',
    '{"kind":"kpi"}'::jsonb,
    '[{"source_span_id":"00000000-0000-0000-0000-000000000801"}]'::jsonb,
    'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    'ontology-v1', 'norm-v1', 'val-v1',
    '00000000-0000-0000-0000-000000000201', 'accepted'
);
UPDATE approved_extraction_records
SET current_version_id = 'b0000000-0000-0000-0000-000000000001', version = 1
WHERE id = 'a0000000-0000-0000-0000-000000000001';
SELECT pg_temp.expect_rejection('approved version immutability', $sql$
    UPDATE approved_extraction_versions SET approval_reason = 'mutated'
    WHERE id = 'b0000000-0000-0000-0000-000000000001'
$sql$);

INSERT INTO confidence_calibrators (
    id, output_family, version, dataset_id, dataset_hash, breakpoints,
    sample_count, artifact_hash
) VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'kpi', 'v1', 'eval-fixture-1',
    'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    '[{"x":0.5,"y":0.5}]'::jsonb, 10,
    'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
);
SELECT pg_temp.expect_rejection('calibrator immutability', $sql$
    UPDATE confidence_calibrators SET sample_count = 11
    WHERE id = 'c0000000-0000-0000-0000-000000000001'
$sql$);

UPDATE extraction_runs
SET status = 'waiting_review'
WHERE id = '60000000-0000-0000-0000-000000000001';
UPDATE extraction_runs
SET status = 'succeeded', finished_at = now()
WHERE id = '60000000-0000-0000-0000-000000000001';
SELECT pg_temp.expect_rejection('event after terminal', $sql$
    INSERT INTO extraction_run_events (org_id, run_id, event_type)
    VALUES (
        '00000000-0000-0000-0000-000000000101',
        '60000000-0000-0000-0000-000000000001',
        'heartbeat'
    )
$sql$);
SELECT pg_temp.expect_rejection('terminal run mutation', $sql$
    UPDATE extraction_runs SET cost_usd = 1
    WHERE id = '60000000-0000-0000-0000-000000000001'
$sql$);
-- G2: proposal 80..01 belongs to run 1, now terminal; the review lifecycle
-- can no longer advance the proposal's state/version.
SELECT pg_temp.expect_rejection('proposal update after terminal run', $sql$
    UPDATE extraction_proposals SET state = 'accepted', version = 3
    WHERE id = '80000000-0000-0000-0000-000000000001'
$sql$, ARRAY['P0001']);

SET LOCAL ROLE fel_app;
SELECT set_config(
    'request.jwt.claims',
    '{"org_id":"00000000-0000-0000-0000-000000000101"}',
    true
);
DO $$
BEGIN
    IF (SELECT count(*) FROM extraction_runs
            WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0
       OR (SELECT count(*) FROM extraction_proposals
            WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0
       OR (SELECT count(*) FROM extraction_reviews
            WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0
       OR (SELECT count(*) FROM approved_extraction_versions
            WHERE org_id = '00000000-0000-0000-0000-000000000102') <> 0 THEN
        RAISE EXCEPTION 'cross-organization extraction rows are visible to fel_app';
    END IF;
    IF (SELECT count(*) FROM confidence_calibrators) < 1 THEN
        RAISE EXCEPTION 'shared calibrators must remain SELECT-visible';
    END IF;
END
$$;
SELECT pg_temp.expect_rejection(
    'RLS rejects cross-organization run insert',
    $sql$
        INSERT INTO extraction_runs (
            id, org_id, workspace_id, entity_id, modes, as_of, corpus_version_id,
            ontology_version, workflow_version, provider, model, policy_id,
            input_hash, idempotency_key, created_by
        ) VALUES (
            '60000000-0000-0000-0000-000000000018',
            '00000000-0000-0000-0000-000000000102',
            '00000000-0000-0000-0000-000000000302',
            '00000000-0000-0000-0000-000000000402',
            ARRAY['kpi']::text[], now(),
            '00000000-0000-0000-0000-000000000b02',
            'ontology-v1', 'workflow-v1', 'mock', 'mock-structured-v1',
            '50000000-0000-0000-0000-000000000002',
            'sha256:9999999999999999999999999999999999999999999999999999999999999999',
            'idem-rls-bad', '00000000-0000-0000-0000-000000000202'
        )
    $sql$,
    ARRAY['42501']
);
RESET ROLE;

DO $$
BEGIN
    RAISE NOTICE 'ok - all extraction migration regression cases passed';
END
$$;
ROLLBACK;
