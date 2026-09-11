-- ADR-0024. Deploy only with compatible extraction workers (old workers drained).
-- Existing financial hashes, NULL legacy occurrences and approvals are unchanged.
ALTER TABLE extraction_runs ADD COLUMN cancel_requested_at timestamptz;
GRANT UPDATE (cancel_requested_at) ON extraction_runs TO fel_app;
ALTER TABLE approved_extraction_versions ADD COLUMN validation_context jsonb;

ALTER TABLE extraction_conflicts ADD COLUMN occurrence_run_id uuid;
ALTER TABLE extraction_conflicts ADD CONSTRAINT extraction_conflicts_occurrence_run_fk
    FOREIGN KEY (occurrence_run_id, org_id, workspace_id)
    REFERENCES extraction_runs (id, org_id, workspace_id);
ALTER TABLE extraction_conflicts
    DROP CONSTRAINT extraction_conflicts_org_id_workspace_id_conflict_key_key;
ALTER TABLE extraction_conflicts ADD CONSTRAINT extraction_conflicts_occurrence_key
    UNIQUE NULLS NOT DISTINCT (org_id, workspace_id, conflict_key, occurrence_run_id);

-- Row locks require UPDATE privilege. Workers may lock via this existing mutable
-- column but the guard below forbids rewriting a completed adjudication.
GRANT UPDATE (status) ON extraction_conflicts TO fel_worker;

CREATE OR REPLACE FUNCTION fel_guard_extraction_conflict() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'extraction_conflicts cannot be deleted';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.org_id IS DISTINCT FROM OLD.org_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.conflict_key IS DISTINCT FROM OLD.conflict_key
       OR NEW.occurrence_run_id IS DISTINCT FROM OLD.occurrence_run_id
       OR NEW.reason_codes IS DISTINCT FROM OLD.reason_codes
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'extraction conflict identity pins are immutable';
    END IF;
    IF current_user = 'fel_worker' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'worker cannot adjudicate extraction conflicts';
    END IF;
    IF OLD.status <> 'open' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'resolved extraction conflict adjudication is immutable';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION fel_guard_extraction_conflict_member() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    member_run uuid;
    member_workspace uuid;
    group_workspace uuid;
    group_run uuid;
    group_status text;
BEGIN
    -- Exact append-only retry adds no data and must retain ON CONFLICT no-op
    -- behavior even after review has closed its run/group. Other orgs/tuples
    -- cannot use this bypass; RLS remains active for every query below.
    IF EXISTS (
        SELECT 1 FROM extraction_conflict_members
        WHERE conflict_id = NEW.conflict_id AND proposal_id = NEW.proposal_id
          AND org_id = NEW.org_id
    ) THEN
        RETURN NEW;
    END IF;
    SELECT run_id, workspace_id INTO member_run, member_workspace
      FROM extraction_proposals WHERE id = NEW.proposal_id AND org_id = NEW.org_id;
    IF member_run IS NULL THEN
        RAISE EXCEPTION 'conflict member has no same-organization proposal';
    END IF;
    -- Same lock order as review: parent runs BEFORE groups. This also fences
    -- terminalization and prevents an API run->group / worker group->run cycle.
    PERFORM fel_assert_extraction_run_open(member_run, NEW.org_id);
    SELECT workspace_id, occurrence_run_id, status
      INTO group_workspace, group_run, group_status
      FROM extraction_conflicts WHERE id = NEW.conflict_id AND org_id = NEW.org_id
      FOR UPDATE;
    IF group_workspace IS NULL OR group_workspace <> member_workspace THEN
        RAISE EXCEPTION 'conflict member must share group organization and workspace';
    END IF;
    IF group_status <> 'open' THEN
        RAISE EXCEPTION 'cannot append to resolved extraction conflict';
    END IF;
    IF group_run IS NOT NULL AND group_run <> member_run THEN
        RAISE EXCEPTION 'conflict member must belong to occurrence run';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER extraction_conflict_members_guard
    BEFORE INSERT ON extraction_conflict_members
    FOR EACH ROW EXECUTE FUNCTION fel_guard_extraction_conflict_member();

COMMENT ON COLUMN extraction_runs.cancel_requested_at IS
    'ADR-0024 durable cancellation acknowledgement; queued/running also flag bound job.';
COMMENT ON COLUMN approved_extraction_versions.validation_context IS
    'Immutable approval-time validation policy and source pins; historical NULL is unknown.';
COMMENT ON COLUMN extraction_conflicts.occurrence_run_id IS
    'ADR-0024 run/v1 occurrence; NULL preserves the legacy workspace-wide key.';
