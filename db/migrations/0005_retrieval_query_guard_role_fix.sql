-- Fix: fel_guard_query() locked retrieval_index_versions with FOR SHARE.
-- Row locks require UPDATE privilege, but shared index artifacts are
-- deliberately SELECT-only to fel_app (ADR-0006 tenancy model), so every
-- application INSERT INTO queries raised 42501 under the request role —
-- the guard could never pass for the very role the API runs as. The 0003
-- harness missed it because guards there run as the superuser, where the
-- lock is permitted (regression covered by tests/0005_*.test.sql, which
-- exercises the insert as fel_app).
--
-- The lock is unnecessary: a queries row may only pin a ready/superseded
-- index version, and published rows are immutable (identity frozen;
-- ready -> superseded keeps published_at and stays pinnable), so a plain
-- read cannot race into an invalid pin. Function body is otherwise
-- identical to 0003.

CREATE OR REPLACE FUNCTION fel_guard_query() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    index_status text;
    index_published_at timestamptz;
    workspace_cutoff timestamptz;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'queries are immutable';
    END IF;
    SELECT status, published_at INTO index_status, index_published_at
    FROM retrieval_index_versions
    WHERE id = NEW.index_version_id;
    IF index_status NOT IN ('ready', 'superseded')
       OR index_published_at IS NULL THEN
        RAISE EXCEPTION 'queries must pin a published retrieval index';
    END IF;
    SELECT as_of INTO workspace_cutoff
    FROM workspaces
    WHERE id = NEW.workspace_id AND org_id = NEW.org_id;
    IF workspace_cutoff IS NOT NULL
       AND NEW.effective_as_of > workspace_cutoff THEN
        RAISE EXCEPTION 'query cutoff cannot exceed its workspace cutoff';
    END IF;
    RETURN NEW;
END
$$;
