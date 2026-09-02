\set ON_ERROR_STOP on

BEGIN;

\ir _helpers.sql

-- Two tenants, so the cancellation grant can be exercised positively (own
-- org) and negatively (another org). Distinct 0x0007 id block.
INSERT INTO organizations (id, name) VALUES
    ('00000000-0000-0000-0000-000000070101', 'Jobs Hardening Org A'),
    ('00000000-0000-0000-0000-000000070102', 'Jobs Hardening Org B');
INSERT INTO memberships (org_id, user_id, role) VALUES
    ('00000000-0000-0000-0000-000000070101', '00000000-0000-0000-0000-000000070201', 'owner'),
    ('00000000-0000-0000-0000-000000070102', '00000000-0000-0000-0000-000000070202', 'owner');

-- ---------------------------------------------------------------------------
-- Columns and indexes exist with the shape queue.py depends on.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'available_at'
          AND is_nullable = 'NO' AND column_default LIKE 'now()%'
    ) THEN
        RAISE EXCEPTION 'not ok - jobs.available_at must be NOT NULL DEFAULT now()';
    END IF;
    IF NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name IN ('started_at', 'cancel_requested_at')
        GROUP BY table_name HAVING count(*) = 2
    ) THEN
        RAISE EXCEPTION 'not ok - jobs is missing started_at/cancel_requested_at';
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_indexes
        WHERE tablename = 'jobs' AND indexname = 'jobs_heartbeat_running_idx'
          AND indexdef LIKE '%heartbeat_at%' AND indexdef LIKE '%''running''%'
    ) THEN
        RAISE EXCEPTION 'not ok - reaper predicate index is missing';
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_indexes
        WHERE tablename = 'jobs' AND indexname = 'jobs_claim_available_idx'
          AND indexdef LIKE '%available_at%' AND indexdef LIKE '%''queued''%'
    ) THEN
        RAISE EXCEPTION 'not ok - claim index does not cover available_at';
    END IF;
    RAISE NOTICE 'ok - 0007 columns and indexes present';
END
$$;

-- ---------------------------------------------------------------------------
-- Case 1: an exhausted stale running job becomes failed, not queued.
-- This is the poison-job loop from #189: reap_stale used to requeue every
-- stale row forever. The SQL below is the reaper's statement.
-- ---------------------------------------------------------------------------
INSERT INTO jobs (id, kind, queue, status, attempts, max_attempts, heartbeat_at, org_id) VALUES
    -- exhausted: attempts = max_attempts
    ('00000000-0000-0000-0000-000000070301', 'poison', 'ingestion', 'running', 5, 5,
     now() - interval '10 minutes', '00000000-0000-0000-0000-000000070101'),
    -- retries left: attempts < max_attempts
    ('00000000-0000-0000-0000-000000070302', 'flaky', 'ingestion', 'running', 1, 5,
     now() - interval '10 minutes', '00000000-0000-0000-0000-000000070101');

UPDATE jobs SET
    status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
    lease = NULL,
    available_at = CASE WHEN attempts < max_attempts THEN now() ELSE available_at END,
    finished_at = CASE WHEN attempts < max_attempts THEN finished_at ELSE now() END,
    error = CASE
        WHEN attempts < max_attempts THEN error
        ELSE jsonb_build_object('error', jsonb_build_object(
            'code', 'REAPED_EXHAUSTED',
            'message', 'stale claim reaped with no attempts remaining',
            'request_id', id::text))
    END
WHERE status = 'running'
  AND heartbeat_at < now() - make_interval(secs => 60);

DO $$
DECLARE
    exhausted jobs;
    retryable jobs;
BEGIN
    SELECT * INTO exhausted FROM jobs WHERE id = '00000000-0000-0000-0000-000000070301';
    IF exhausted.status <> 'failed' THEN
        RAISE EXCEPTION 'not ok - exhausted stale job was requeued as % (poison loop)',
            exhausted.status;
    END IF;
    IF exhausted.error -> 'error' ->> 'code' <> 'REAPED_EXHAUSTED' THEN
        RAISE EXCEPTION 'not ok - exhausted stale job has no REAPED_EXHAUSTED envelope';
    END IF;
    IF exhausted.error -> 'error' ->> 'request_id' <> exhausted.id::text THEN
        RAISE EXCEPTION 'not ok - error envelope request_id must be the job id';
    END IF;
    IF exhausted.finished_at IS NULL OR exhausted.lease IS NOT NULL THEN
        RAISE EXCEPTION 'not ok - dead-lettered job must be finished and lease-free';
    END IF;

    SELECT * INTO retryable FROM jobs WHERE id = '00000000-0000-0000-0000-000000070302';
    IF retryable.status <> 'queued' THEN
        RAISE EXCEPTION 'not ok - stale job with attempts remaining must requeue, got %',
            retryable.status;
    END IF;
    RAISE NOTICE 'ok - exhausted stale job dead-letters, non-exhausted requeues';
END
$$;

-- ---------------------------------------------------------------------------
-- Case 2: a failed attempt scheduled into the future is not claimable until
-- available_at passes. This is the claim_one predicate.
-- ---------------------------------------------------------------------------
INSERT INTO jobs (id, kind, queue, status, attempts, max_attempts, available_at, org_id) VALUES
    ('00000000-0000-0000-0000-000000070303', 'backoff', 'backoff-q', 'queued', 1, 5,
     now() + interval '5 minutes', '00000000-0000-0000-0000-000000070101');

DO $$
DECLARE
    claimable uuid;
BEGIN
    SELECT id INTO claimable FROM jobs
    WHERE queue = 'backoff-q' AND status = 'queued' AND available_at <= now()
    ORDER BY priority, created_at
    LIMIT 1;
    IF claimable IS NOT NULL THEN
        RAISE EXCEPTION 'not ok - a backed-off job was claimable before available_at';
    END IF;

    -- Once the backoff elapses the same predicate returns it.
    UPDATE jobs SET available_at = now() - interval '1 second'
    WHERE id = '00000000-0000-0000-0000-000000070303';
    SELECT id INTO claimable FROM jobs
    WHERE queue = 'backoff-q' AND status = 'queued' AND available_at <= now()
    ORDER BY priority, created_at
    LIMIT 1;
    IF claimable IS DISTINCT FROM '00000000-0000-0000-0000-000000070303'::uuid THEN
        RAISE EXCEPTION 'not ok - job stayed unclaimable after its backoff elapsed';
    END IF;
    RAISE NOTICE 'ok - available_at gates the claim predicate in both directions';
END
$$;

-- ---------------------------------------------------------------------------
-- Case 3: fel_app may request cancellation on its own org's job only.
-- Superuser-only coverage cannot catch grant/RLS bugs (README harness
-- convention), so every assertion below runs under SET LOCAL ROLE fel_app.
-- ---------------------------------------------------------------------------
INSERT INTO jobs (id, kind, queue, status, org_id) VALUES
    ('00000000-0000-0000-0000-000000070401', 'extraction_run', 'ingestion', 'running',
     '00000000-0000-0000-0000-000000070101'),
    ('00000000-0000-0000-0000-000000070402', 'extraction_run', 'ingestion', 'running',
     '00000000-0000-0000-0000-000000070102'),
    -- platform job with no tenant: readable by everyone, cancellable by no one
    ('00000000-0000-0000-0000-000000070403', 'platform_sweep', 'ingestion', 'running', NULL);

SET LOCAL ROLE fel_app;
SELECT set_config(
    'request.jwt.claims',
    '{"org_id":"00000000-0000-0000-0000-000000070101"}',
    true
);

UPDATE jobs SET cancel_requested_at = now()
WHERE id = '00000000-0000-0000-0000-000000070401';
DO $$
BEGIN
    IF (SELECT cancel_requested_at FROM jobs
        WHERE id = '00000000-0000-0000-0000-000000070401') IS NULL THEN
        RAISE EXCEPTION 'not ok - fel_app could not request cancellation on its own job';
    END IF;
    RAISE NOTICE 'ok - fel_app can set cancel_requested_at on its own org job';
END
$$;

-- Another org's job is invisible under jobs_tenant, so the UPDATE matches
-- nothing rather than erroring: assert the row was NOT touched.
UPDATE jobs SET cancel_requested_at = now()
WHERE id = '00000000-0000-0000-0000-000000070402';
-- The tenantless platform job IS visible (jobs_tenant permits org_id IS NULL)
-- but the restrictive jobs_cancel_own_org policy must keep it uncancellable.
UPDATE jobs SET cancel_requested_at = now()
WHERE id = '00000000-0000-0000-0000-000000070403';

-- Every other column stays read-only to fel_app: the grant is column-level,
-- so touching status must fail with 42501 even on its own org's row.
SELECT pg_temp.expect_rejection(
    'fel_app writing jobs.status',
    $sql$
        UPDATE jobs SET status = 'cancelled'
        WHERE id = '00000000-0000-0000-0000-000000070401'
    $sql$,
    ARRAY['42501']
);
SELECT pg_temp.expect_rejection(
    'fel_app writing jobs.attempts',
    $sql$
        UPDATE jobs SET attempts = 0
        WHERE id = '00000000-0000-0000-0000-000000070401'
    $sql$,
    ARRAY['42501']
);
RESET ROLE;

DO $$
BEGIN
    IF (SELECT cancel_requested_at FROM jobs
        WHERE id = '00000000-0000-0000-0000-000000070402') IS NOT NULL THEN
        RAISE EXCEPTION 'not ok - fel_app cancelled another org''s job';
    END IF;
    RAISE NOTICE 'ok - fel_app cannot set cancel_requested_at on another org job';
    IF (SELECT cancel_requested_at FROM jobs
        WHERE id = '00000000-0000-0000-0000-000000070403') IS NOT NULL THEN
        RAISE EXCEPTION 'not ok - fel_app cancelled a tenantless platform job';
    END IF;
    RAISE NOTICE 'ok - fel_app cannot cancel a tenantless platform job';
    IF (SELECT status FROM jobs
        WHERE id = '00000000-0000-0000-0000-000000070401') <> 'running' THEN
        RAISE EXCEPTION 'not ok - fel_app changed jobs.status';
    END IF;
END
$$;

DO $$ BEGIN RAISE NOTICE 'ok - all 0007 jobs-hardening cases passed'; END $$;

ROLLBACK;
