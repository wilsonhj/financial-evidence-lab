\set ON_ERROR_STOP on
BEGIN;
\ir _helpers.sql

INSERT INTO organizations (id,name) VALUES
 ('27800000-0000-4000-8000-000000000001','Review test'),
 ('27800000-0000-4000-8000-000000000002','Other tenant');
INSERT INTO memberships (org_id,user_id,role) VALUES
 ('27800000-0000-4000-8000-000000000001','27800000-0000-4000-8000-000000000003','owner');
INSERT INTO workspaces (id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of) VALUES
 ('27800000-0000-4000-8000-000000000004','27800000-0000-4000-8000-000000000001',
  'Review','27800000-0000-4000-8000-000000000005','USD','calendar',now());
INSERT INTO corpus_versions (id,label,status,is_active,published_at) VALUES
 ('27800000-0000-4000-8000-000000000006','Review corpus','active',true,now());
INSERT INTO extraction_policies (id,org_id,version,created_by) VALUES
 ('27800000-0000-4000-8000-000000000007','27800000-0000-4000-8000-000000000001',1,
  '27800000-0000-4000-8000-000000000003');
INSERT INTO extraction_runs (id,org_id,workspace_id,entity_id,modes,as_of,corpus_version_id,
 ontology_version,workflow_version,provider,model,policy_id,input_hash,idempotency_key,created_by)
SELECT ('27800000-0000-4000-8000-' || lpad(n::text,12,'0'))::uuid,
 '27800000-0000-4000-8000-000000000001','27800000-0000-4000-8000-000000000004',
 '27800000-0000-4000-8000-000000000005',ARRAY['kpi'],now(),
 '27800000-0000-4000-8000-000000000006','saas-metrics/v1','extraction-workflow/v3',
 'mock','mock-structured-v1','27800000-0000-4000-8000-000000000007',
 'sha256:' || repeat('a',64),'review-run-' || n,'27800000-0000-4000-8000-000000000003'
FROM generate_series(10,11) n;
UPDATE extraction_runs SET status='running' WHERE org_id='27800000-0000-4000-8000-000000000001';
INSERT INTO extraction_conflicts (id,org_id,workspace_id,conflict_key,occurrence_run_id)
SELECT ('27800000-0000-4000-8000-' || lpad(n::text,12,'0'))::uuid,
 '27800000-0000-4000-8000-000000000001','27800000-0000-4000-8000-000000000004',
 'same-financial-key',CASE WHEN n=20 THEN NULL ELSE
 ('27800000-0000-4000-8000-' || lpad((n-11)::text,12,'0'))::uuid END
FROM generate_series(20,22) n;
SELECT pg_temp.expect_rejection('legacy NULL uniqueness', $sql$
 INSERT INTO extraction_conflicts(id,org_id,workspace_id,conflict_key)
 VALUES ('27800000-0000-4000-8000-000000000029','27800000-0000-4000-8000-000000000001',
 '27800000-0000-4000-8000-000000000004','same-financial-key')
$sql$, ARRAY['23505']);
SELECT pg_temp.expect_rejection('occurrence run tenant/workspace FK', $sql$
 INSERT INTO extraction_conflicts(id,org_id,workspace_id,conflict_key,occurrence_run_id)
 VALUES ('27800000-0000-4000-8000-000000000029','27800000-0000-4000-8000-000000000001',
 '27800000-0000-4000-8000-000000000004','bad-run','27800000-0000-4000-8000-000000000099')
$sql$, ARRAY['23503']);
SELECT pg_temp.expect_rejection('occurrence identity immutable', $sql$
 UPDATE extraction_conflicts SET occurrence_run_id=NULL
 WHERE id='27800000-0000-4000-8000-000000000021'
$sql$, ARRAY['P0001']);

INSERT INTO extraction_proposals(id,org_id,workspace_id,run_id,kind,metric_id,payload,
 raw_payload_hash,definition_hash,state)
SELECT ('27800000-0000-4000-8000-' || lpad(n::text,12,'0'))::uuid,
 '27800000-0000-4000-8000-000000000001','27800000-0000-4000-8000-000000000004',
 CASE WHEN n=32 THEN '27800000-0000-4000-8000-000000000011'::uuid ELSE
 '27800000-0000-4000-8000-000000000010'::uuid END,'kpi','arr','{}',
 'sha256:' || repeat('b',64),'sha256:' || repeat('c',64),'needs_review'
FROM generate_series(30,32) n;
SET LOCAL ROLE fel_worker;
INSERT INTO extraction_conflict_members(conflict_id,proposal_id,org_id) VALUES
 ('27800000-0000-4000-8000-000000000021','27800000-0000-4000-8000-000000000030',
 '27800000-0000-4000-8000-000000000001');
SELECT pg_temp.expect_rejection('worker cannot adjudicate despite lock grant', $sql$
 UPDATE extraction_conflicts SET status='resolved'
 WHERE id='27800000-0000-4000-8000-000000000021'
$sql$, ARRAY['P0001']);
SELECT pg_temp.expect_rejection('worker cross-run membership rejected', $sql$
 INSERT INTO extraction_conflict_members(conflict_id,proposal_id,org_id) VALUES
 ('27800000-0000-4000-8000-000000000021','27800000-0000-4000-8000-000000000032',
 '27800000-0000-4000-8000-000000000001')
$sql$, ARRAY['P0001']);
RESET ROLE;
SELECT set_config('request.jwt.claims',
 '{"org_id":"27800000-0000-4000-8000-000000000001","sub":"27800000-0000-4000-8000-000000000003","role":"owner"}',true);
SET LOCAL ROLE fel_app;
UPDATE extraction_runs SET cancel_requested_at=now()
 WHERE id='27800000-0000-4000-8000-000000000010';
UPDATE extraction_conflicts SET status='resolved',resolved_by='27800000-0000-4000-8000-000000000003',
 resolved_at=now(),resolution_note='Cited winner' WHERE id='27800000-0000-4000-8000-000000000021';
SELECT pg_temp.expect_rejection('resolved history cannot reopen', $sql$
 UPDATE extraction_conflicts SET status='open',resolved_by=NULL,resolved_at=NULL
 WHERE id='27800000-0000-4000-8000-000000000021'
$sql$, ARRAY['P0001']);
SELECT pg_temp.expect_rejection('resolved reason cannot change', $sql$
 UPDATE extraction_conflicts SET resolution_note='rewritten'
 WHERE id='27800000-0000-4000-8000-000000000021'
$sql$, ARRAY['P0001']);
INSERT INTO extraction_conflict_members(conflict_id,proposal_id,org_id) VALUES
 ('27800000-0000-4000-8000-000000000021','27800000-0000-4000-8000-000000000030',
 '27800000-0000-4000-8000-000000000001') ON CONFLICT DO NOTHING;
SELECT pg_temp.expect_rejection('resolved new member cannot append', $sql$
 INSERT INTO extraction_conflict_members(conflict_id,proposal_id,org_id) VALUES
 ('27800000-0000-4000-8000-000000000021','27800000-0000-4000-8000-000000000031',
 '27800000-0000-4000-8000-000000000001') ON CONFLICT DO NOTHING
$sql$, ARRAY['P0001']);
RESET ROLE;
SELECT set_config('request.jwt.claims','{"org_id":"27800000-0000-4000-8000-000000000002"}',true);
SET LOCAL ROLE fel_app;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM extraction_conflicts WHERE org_id='27800000-0000-4000-8000-000000000001') THEN
  RAISE EXCEPTION 'other tenant can see extraction conflict';
 END IF;
END $$;
RESET ROLE;
DO $$ BEGIN
 IF (SELECT count(*) FROM extraction_conflict_members
     WHERE conflict_id='27800000-0000-4000-8000-000000000021') <> 1 THEN
  RAISE EXCEPTION 'rejected member changed history';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM extraction_runs WHERE id='27800000-0000-4000-8000-000000000010'
                AND cancel_requested_at IS NOT NULL AND version=1) THEN
  RAISE EXCEPTION 'cancellation marker changed stored run version or was not written';
 END IF;
END $$;
ROLLBACK;
