-- Jobs hardening (issue #189): retry scheduling, reaper support, cancellation.
--
-- 0001 shipped the queue with three gaps that only show up under load:
--
--   1. the reaper predicate (status = 'running' AND heartbeat_at < ...) had no
--      supporting index, so every reap swept the whole table;
--   2. a failed job was requeued for an immediate re-claim, so a job failing
--      on a transient dependency hot-loops through its attempts budget;
--   3. `fel_app` could enqueue and read jobs but had no way to ask for one to
--      be cancelled, so cancellation had to run as the service role.
--
-- Additive only: three nullable/defaulted columns, two indexes, one
-- column-level grant and one restrictive RLS policy. No existing column,
-- constraint, policy or grant is altered, and every statement is guarded so
-- re-applying the file is a no-op (the repository applies migrations in
-- lexical order against both fresh and already-migrated databases).

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now();
COMMENT ON COLUMN jobs.available_at IS
    'Earliest instant the job may be claimed. Retry backoff pushes it into the '
    'future; claim_one filters on available_at <= now().';

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at timestamptz;
COMMENT ON COLUMN jobs.started_at IS
    'Instant of the most recent successful claim; reset on every claim, so it '
    'pairs with attempts rather than with created_at.';

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cancel_requested_at timestamptz;
COMMENT ON COLUMN jobs.cancel_requested_at IS
    'Cooperative cancellation request. Setting it never changes status: the '
    'worker observes the flag at a stage boundary and finishes the job itself.';

-- (1) Reaper predicate. Partial on status = 'running' because running rows are
-- a small, short-lived slice of the table; heartbeat_at leads so the reaper's
-- range scan is served directly.
CREATE INDEX IF NOT EXISTS jobs_heartbeat_running_idx
    ON jobs (heartbeat_at) WHERE status = 'running';

-- (2) Claim predicate. 0001's jobs_claim_idx stays as it is (append-only
-- rule: never edit an applied migration); this one is the same key with
-- available_at as an INCLUDE payload. The key order is deliberately
-- unchanged: claim_one still needs rows in (priority, created_at) order, and
-- moving available_at into the key would cost a sort for the common case
-- where nothing is backed off. As an INCLUDE column, `available_at <= now()`
-- is evaluated from the index instead of a heap fetch per scheduled retry.
CREATE INDEX IF NOT EXISTS jobs_claim_available_idx
    ON jobs (queue, priority, created_at) INCLUDE (available_at)
    WHERE status = 'queued';

-- (3) Cancellation for the application role. jobs has RLS (0001's permissive
-- jobs_tenant policy covers ALL commands), so two things are needed and
-- neither is sufficient alone:
--
--   * a column-level UPDATE grant, so fel_app can write cancel_requested_at
--     and nothing else — not status, attempts, lease, payload or error;
--   * a RESTRICTIVE policy for UPDATE. jobs_tenant permits `org_id IS NULL`
--     (platform jobs with no tenant) as well as the caller's own org. That is
--     right for reading, but a tenant must not be able to cancel a platform
--     job, so this policy ANDs an own-org-only requirement onto UPDATE alone
--     and leaves SELECT/INSERT untouched. It is scoped `TO fel_app` so the
--     future non-superuser worker service role (see README) does not inherit
--     a rule written for request paths.
GRANT UPDATE (cancel_requested_at) ON jobs TO fel_app;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'jobs'
          AND policyname = 'jobs_cancel_own_org'
    ) THEN
        CREATE POLICY jobs_cancel_own_org ON jobs
            AS RESTRICTIVE FOR UPDATE TO fel_app
            USING (org_id = fel_claim_org_id())
            WITH CHECK (org_id = fel_claim_org_id());
    END IF;
END
$$;
