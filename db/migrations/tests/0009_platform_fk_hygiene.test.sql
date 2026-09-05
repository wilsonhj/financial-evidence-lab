-- Harness for 0009_platform_fk_hygiene.sql (issue #197).
--
-- One assertion per table: an org_id naming an organization that does not
-- exist must be refused with 23503 (foreign_key_violation). Plus the two
-- contracts the FK must NOT break — a real org still inserts, and
-- jobs.org_id stays nullable for platform jobs.

\set ON_ERROR_STOP on

BEGIN;

\ir _helpers.sql

INSERT INTO organizations (id, name)
VALUES ('00000000-0000-0000-0000-0000000009f9', 'FK Hygiene Org');

-- Unknown organization: rejected on every one of the three columns.
SELECT pg_temp.expect_rejection('audit_events rejects unknown org', $sql$
    INSERT INTO audit_events (org_id, action, object_type)
    VALUES ('00000000-0000-0000-0000-00000000dead', 'test.action', 'thing')
$sql$, ARRAY['23503']);

SELECT pg_temp.expect_rejection('usage_events rejects unknown org', $sql$
    INSERT INTO usage_events (org_id, user_id, kind, cost_usd)
    VALUES (
        '00000000-0000-0000-0000-00000000dead',
        '00000000-0000-0000-0000-0000000009b9', 'tokens', 1.5
    )
$sql$, ARRAY['23503']);

SELECT pg_temp.expect_rejection('jobs rejects unknown org', $sql$
    INSERT INTO jobs (id, kind, payload, org_id)
    VALUES (
        '00000000-0000-0000-0000-0000000008f9', 'sec_filing_fetch', '{}'::jsonb,
        '00000000-0000-0000-0000-00000000dead'
    )
$sql$, ARRAY['23503']);

-- Known organization: unchanged behaviour.
INSERT INTO audit_events (org_id, action, object_type)
VALUES ('00000000-0000-0000-0000-0000000009f9', 'test.action', 'thing');
INSERT INTO usage_events (org_id, user_id, kind, cost_usd)
VALUES (
    '00000000-0000-0000-0000-0000000009f9',
    '00000000-0000-0000-0000-0000000009b9', 'tokens', 1.5
);
INSERT INTO jobs (id, kind, payload, org_id)
VALUES (
    '00000000-0000-0000-0000-0000000008f8', 'sec_filing_fetch', '{}'::jsonb,
    '00000000-0000-0000-0000-0000000009f9'
);

-- Platform jobs carry no tenant: NULL must remain legal under the new FK.
INSERT INTO jobs (id, kind, payload)
VALUES ('00000000-0000-0000-0000-0000000008f7', 'sec_discovery', '{}'::jsonb);

-- ON DELETE RESTRICT: an organization with audit/usage/job history cannot be
-- silently removed out from under it.
SELECT pg_temp.expect_rejection('organization delete is restricted by references', $sql$
    DELETE FROM organizations WHERE id = '00000000-0000-0000-0000-0000000009f9'
$sql$, ARRAY['23503']);

-- The M4 placeholder is documented, not constrained.
DO $$
BEGIN
    IF col_description('workspaces'::regclass,
                       (SELECT attnum FROM pg_attribute
                         WHERE attrelid = 'workspaces'::regclass
                           AND attname = 'active_scenario_id')) IS NULL THEN
        RAISE EXCEPTION 'not ok - workspaces.active_scenario_id is undocumented';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'workspaces'::regclass
          AND contype = 'f'
          AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                               WHERE attrelid = 'workspaces'::regclass
                                 AND attname = 'active_scenario_id')]::smallint[]
    ) THEN
        RAISE EXCEPTION 'not ok - active_scenario_id gained an FK without a scenarios table';
    END IF;
    RAISE NOTICE 'ok - active_scenario_id documented as M4-reserved with no FK';
END
$$;

-- Every new constraint is VALIDATED, not left NOT VALID (an unvalidated
-- constraint checks new rows but silently tolerates existing violations).
DO $$
DECLARE
    unvalidated text;
BEGIN
    SELECT string_agg(conname, ', ') INTO unvalidated
    FROM pg_constraint
    WHERE conname IN (
        'audit_events_org_id_fkey', 'usage_events_org_id_fkey', 'jobs_org_id_fkey'
    ) AND NOT convalidated;
    IF unvalidated IS NOT NULL THEN
        RAISE EXCEPTION 'not ok - constraints left NOT VALID: %', unvalidated;
    END IF;
    IF (SELECT count(*) FROM pg_constraint
        WHERE conname IN (
            'audit_events_org_id_fkey', 'usage_events_org_id_fkey', 'jobs_org_id_fkey'
        )) <> 3 THEN
        RAISE EXCEPTION 'not ok - expected three org_id foreign keys';
    END IF;
    RAISE NOTICE 'ok - all three org_id foreign keys exist and are validated';
END
$$;

DO $$
BEGIN
    RAISE NOTICE 'ok - all platform FK hygiene cases passed';
END
$$;

ROLLBACK;
