-- Platform FK hygiene (issue #197).
--
-- 0001 gave `memberships` and `workspaces` a real FK to `organizations` but
-- left `audit_events.org_id`, `usage_events.org_id` and `jobs.org_id` as bare
-- uuid columns. Nothing but RLS stopped a row naming an organization that
-- never existed — and RLS is not a referential check: the API role writes the
-- org_id straight from its claims, and a stale or malformed claim wrote an
-- orphan audit/usage/job row that no tenant can ever read back and no
-- cascade-free delete of an organization would ever surface. Metering and the
-- audit trail are the two places an orphan is most expensive: they are the
-- billing and compliance record.
--
-- ON DELETE RESTRICT (never CASCADE): audit and usage rows are append-only
-- evidence, so an organization carrying them must not be deletable by
-- accident. `jobs.org_id` stays NULLABLE (platform jobs carry no tenant);
-- a foreign key permits NULL, so that contract is unchanged.
--
-- NOT VALID + VALIDATE CONSTRAINT keeps the ALTER off an ACCESS EXCLUSIVE
-- full-table scan: the NOT VALID step takes the lock only long enough to add
-- the catalog entry (new rows are checked immediately) and VALIDATE then
-- scans under SHARE UPDATE EXCLUSIVE, which does not block reads or writes.

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_org_id_fkey
    FOREIGN KEY (org_id) REFERENCES organizations (id) ON DELETE RESTRICT
    NOT VALID;
ALTER TABLE audit_events VALIDATE CONSTRAINT audit_events_org_id_fkey;

ALTER TABLE usage_events
    ADD CONSTRAINT usage_events_org_id_fkey
    FOREIGN KEY (org_id) REFERENCES organizations (id) ON DELETE RESTRICT
    NOT VALID;
ALTER TABLE usage_events VALIDATE CONSTRAINT usage_events_org_id_fkey;

ALTER TABLE jobs
    ADD CONSTRAINT jobs_org_id_fkey
    FOREIGN KEY (org_id) REFERENCES organizations (id) ON DELETE RESTRICT
    NOT VALID;
ALTER TABLE jobs VALIDATE CONSTRAINT jobs_org_id_fkey;

-- workspaces.active_scenario_id is reserved for the M4 scenario engine; the
-- `scenarios` table does not exist yet, so there is deliberately no FK here.
-- The migration that creates `scenarios` must add it (composite on
-- (active_scenario_id, org_id) so a workspace cannot point at another
-- tenant's scenario) and drop this comment's "no FK yet" clause.
COMMENT ON COLUMN workspaces.active_scenario_id IS
    'Reserved for the M4 scenario engine; no foreign key yet because the '
    'scenarios table does not exist. The migration adding scenarios must add '
    'the (active_scenario_id, org_id) composite foreign key.';
