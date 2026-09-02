-- Worker service role (issue #190, ADR-0013).
--
-- Until now the only non-owner role in the cluster was `fel_app`, the
-- request-path role. Everything on the JOB path — ingestion, the corpus
-- publish, the retrieval index build, extraction persistence — ran as the
-- migration/owner superuser, which bypasses RLS, every grant, and every
-- DDL restriction. A worker bug (or a poisoned job payload) therefore had
-- the whole schema in reach, including DELETE on immutable evidence.
--
-- `fel_worker` is the job path's least-privilege counterpart:
-- * NOLOGIN, granted to whatever login role the deployment uses, and
--   entered per connection with `SET ROLE` (see FEL_WORKER_DB_ROLE in
--   workers/src/fel_workers/storage.py).
-- * No DELETE anywhere, no DDL, no BYPASSRLS, no TRUNCATE, no ownership.
--   Corpus evidence, retrieval artifacts, and extraction records stay
--   append-only from the worker's point of view exactly as they already
--   are from the API's.
-- * The grant list below is derived EMPIRICALLY from the SQL the worker
--   actually executes: workers/src/fel_workers/{queue,consumer}.py,
--   ingestion/{pipeline,raw_store,company_facts}.py,
--   extraction/persist.py, and packages/retrieval/fel_retrieval/
--   {index_build,lanes}.py. Anything not executed there is not granted.
--   Every future worker-written table must extend this set AND its
--   harness (tests/0008_worker_role.test.sql) in the same migration.
--
-- Grant shape: TABLE-level SELECT/INSERT/UPDATE where the worker updates a
-- row wholesale (jobs, extraction_run_steps), column-level UPDATE where the
-- data model already pins which columns may move (extraction_runs, mirroring
-- 0004's fel_app grant). Row locks (`FOR SHARE`/`FOR UPDATE`) inside the
-- 0003/0004 guards require UPDATE privilege on the locked table for the role
-- executing the statement (see db/migrations/README.md and 0005): fel_worker
-- gets UPDATE on retrieval_index_versions (fel_guard_retrieval_item /
-- fel_guard_retrieval_embedding lock it FOR SHARE) and on extraction_runs
-- (fel_assert_extraction_run_open locks it FOR SHARE).
--
-- No sequence grants: every worker-written identity column
-- (extraction_run_events.id) is GENERATED ALWAYS AS IDENTITY, whose implicit
-- sequence is reachable through the table's INSERT privilege; the schema
-- defines no free-standing sequences.
--
-- RLS: corpus and shared retrieval artifacts carry no org_id and no RLS —
-- grants alone govern them. The tenant tables the worker touches have RLS
-- enabled and policies keyed on `fel_claim_org_id()`, which is NULL for a
-- worker (no request claims), so without policies of its own fel_worker
-- would see and write nothing. RLS cannot express tenant isolation for a
-- cross-tenant service: the job path legitimately runs work for every org,
-- and the real tenant boundary is the job -> run binding enforced in
-- fel_workers.extraction.handler plus 0004's guards. The policies below
-- therefore pin ORG CONSISTENCY instead — a child row's org_id must match
-- the org of the run/proposal/conflict/workspace it hangs off — and the
-- two roots the worker must traverse freely (jobs, extraction_runs,
-- workspaces) are permissive but read/update-only.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fel_worker') THEN
        CREATE ROLE fel_worker NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO fel_worker;

-- ---------------------------------------------------------------------------
-- Platform: the durable job queue (workers/src/fel_workers/queue.py)
-- ---------------------------------------------------------------------------

-- claim_one/heartbeat/complete/fail/reap_stale rewrite status, lease,
-- heartbeat_at, attempts, finished_at and error; discovery enqueues follow-up
-- jobs. TABLE-level UPDATE (not a column list) so queue columns added by
-- later migrations are covered without a privilege regression.
GRANT SELECT, INSERT, UPDATE ON jobs TO fel_worker;

-- The queue is cross-tenant by construction (org_id is NULL for platform
-- jobs), so the worker's policy is permissive; DELETE is still refused
-- because no DELETE privilege is granted.
CREATE POLICY jobs_worker ON jobs TO fel_worker
    USING (true)
    WITH CHECK (true);

-- Read-only: extraction/persist.py asserts the run's workspace belongs to
-- the run's org before writing tenant rows.
GRANT SELECT ON workspaces TO fel_worker;
CREATE POLICY workspaces_worker_read ON workspaces FOR SELECT TO fel_worker
    USING (true);

-- ---------------------------------------------------------------------------
-- Corpus (0002): shared public evidence, curated by workers, no RLS
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT ON documents, document_versions, sections, source_spans,
    tables_meta, financial_facts, corpus_version_documents,
    ingestion_quarantine TO fel_worker;
-- corpus_versions: the publish transaction flips draft -> active/superseded.
GRANT SELECT, INSERT, UPDATE ON corpus_versions TO fel_worker;
-- ingestion_runs: the idempotent job ledger is claimed 'running' and then
-- moved to its terminal status.
GRANT SELECT, INSERT, UPDATE ON ingestion_runs TO fel_worker;

-- ---------------------------------------------------------------------------
-- Retrieval (0003): shared immutable index artifacts, no RLS
-- ---------------------------------------------------------------------------

-- index_build.py mints the version row, walks draft -> building -> ready
-- (or failed), and appends items/embeddings while it is 'building'. UPDATE
-- on the version table is also what makes the guards' FOR SHARE lock legal.
GRANT SELECT, INSERT, UPDATE ON retrieval_index_versions TO fel_worker;
GRANT SELECT, INSERT ON retrieval_items, retrieval_embeddings TO fel_worker;

-- ---------------------------------------------------------------------------
-- Extraction (0004): tenant records written by the job path
-- ---------------------------------------------------------------------------

-- Runs are created by the request path; the worker only advances status,
-- usage counters and timestamps. Column list mirrors 0004's fel_app grant
-- (the identity pins are additionally frozen by fel_guard_extraction_run).
GRANT SELECT ON extraction_runs TO fel_worker;
GRANT UPDATE (
    status, calls_used, input_tokens_used, output_tokens_used, cost_usd,
    version, error, started_at, finished_at
) ON extraction_runs TO fel_worker;
-- Steps are inserted per attempt and advanced in place; TABLE-level UPDATE
-- per the same forward-compatibility rule as jobs.
GRANT SELECT, INSERT, UPDATE ON extraction_run_steps TO fel_worker;
-- Append-only children: no UPDATE, no DELETE.
GRANT SELECT, INSERT ON extraction_run_events, extraction_proposals,
    extraction_proposal_evidence, extraction_conflicts,
    extraction_conflict_members TO fel_worker;

-- fel_assert_extraction_run_open is SECURITY INVOKER and locks
-- extraction_runs FOR SHARE on every child write; EXECUTE is granted
-- explicitly rather than relying on the PUBLIC default, so a later
-- REVOKE ... FROM PUBLIC cannot silently break the job path.
GRANT EXECUTE ON FUNCTION fel_assert_extraction_run_open(uuid, uuid) TO fel_worker;
GRANT EXECUTE ON FUNCTION fel_claim_org_id() TO fel_worker;

-- Runs: permissive (cross-tenant by design), but SELECT/UPDATE only.
CREATE POLICY extraction_runs_worker ON extraction_runs TO fel_worker
    USING (true)
    WITH CHECK (true);

-- Children: org_id must agree with the parent run's org.
CREATE POLICY extraction_run_steps_worker ON extraction_run_steps TO fel_worker
    USING (EXISTS (
        SELECT 1 FROM extraction_runs r
        WHERE r.id = extraction_run_steps.run_id
          AND r.org_id = extraction_run_steps.org_id
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM extraction_runs r
        WHERE r.id = extraction_run_steps.run_id
          AND r.org_id = extraction_run_steps.org_id
    ));

CREATE POLICY extraction_run_events_worker ON extraction_run_events TO fel_worker
    USING (EXISTS (
        SELECT 1 FROM extraction_runs r
        WHERE r.id = extraction_run_events.run_id
          AND r.org_id = extraction_run_events.org_id
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM extraction_runs r
        WHERE r.id = extraction_run_events.run_id
          AND r.org_id = extraction_run_events.org_id
    ));

CREATE POLICY extraction_proposals_worker ON extraction_proposals TO fel_worker
    USING (EXISTS (
        SELECT 1 FROM extraction_runs r
        WHERE r.id = extraction_proposals.run_id
          AND r.org_id = extraction_proposals.org_id
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM extraction_runs r
        WHERE r.id = extraction_proposals.run_id
          AND r.org_id = extraction_proposals.org_id
    ));

CREATE POLICY extraction_proposal_evidence_worker
    ON extraction_proposal_evidence TO fel_worker
    USING (EXISTS (
        SELECT 1 FROM extraction_proposals p
        WHERE p.id = extraction_proposal_evidence.proposal_id
          AND p.org_id = extraction_proposal_evidence.org_id
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM extraction_proposals p
        WHERE p.id = extraction_proposal_evidence.proposal_id
          AND p.org_id = extraction_proposal_evidence.org_id
    ));

-- Conflicts carry no run_id; their org is pinned by the workspace they group
-- proposals in.
CREATE POLICY extraction_conflicts_worker ON extraction_conflicts TO fel_worker
    USING (EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = extraction_conflicts.workspace_id
          AND w.org_id = extraction_conflicts.org_id
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = extraction_conflicts.workspace_id
          AND w.org_id = extraction_conflicts.org_id
    ));

CREATE POLICY extraction_conflict_members_worker
    ON extraction_conflict_members TO fel_worker
    USING (EXISTS (
        SELECT 1 FROM extraction_conflicts c
        WHERE c.id = extraction_conflict_members.conflict_id
          AND c.org_id = extraction_conflict_members.org_id
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM extraction_conflicts c
        WHERE c.id = extraction_conflict_members.conflict_id
          AND c.org_id = extraction_conflict_members.org_id
    ));

COMMENT ON ROLE fel_worker IS
    'Job-path service role (ADR-0013): least-privilege counterpart to fel_app. '
    'No DELETE, no DDL, no BYPASSRLS. Entered per connection via SET ROLE when '
    'FEL_WORKER_DB_ROLE is configured.';
