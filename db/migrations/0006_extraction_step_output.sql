-- ADR-0011 (issue #157): give `extraction_run_steps` the `output` column the
-- checkpoint has always needed, so a stage's result stops riding on the
-- `step_completed` event payload and the published "event payloads are
-- metadata-only" guarantee becomes true as written.
--
-- Migration 0004 is NOT edited (README rule: migrations are append-only;
-- correct forward). 0005 is the precedent — it corrected a 0003 defect in a new
-- file.
--
-- What 0004 already provides, verified, and deliberately NOT restated as a
-- change here:
--
--   * Grants. `GRANT SELECT, INSERT, UPDATE ON extraction_run_steps TO fel_app`
--     (0004) is TABLE level, so a column added later is covered automatically.
--     The restatement below is a no-op kept for the reader: it documents that
--     the coverage is intentional. Do NOT generalise it — `extraction_runs`'
--     UPDATE grant is column-scoped, so a new column THERE would need an
--     explicit grant.
--   * RLS. `extraction_run_steps_isolation` is column-agnostic.
--   * Guards. `fel_guard_extraction_run_child` enumerates its immutable pins
--     explicitly and `output` is not among them, so a step may advance it
--     within an open run — which 0004's own comment ("Steps may advance
--     status/output within an open run") already anticipated. The terminal-run
--     guard `fel_assert_extraction_run_open` is unchanged and still rejects
--     every child write once a run is terminal.
--
-- Backfill is impossible, permanently. Every UPDATE on `extraction_run_steps`
-- runs `fel_assert_extraction_run_open`, which raises for terminal runs, and
-- DELETE is rejected unconditionally. Step rows written before this migration
-- on runs that have since gone terminal therefore keep `output_hash` set and
-- `output NULL` forever. Two consequences, both deliberate:
--
--   1. The pair CHECK is added NOT VALID. An eager (validating) constraint
--      would fail against exactly those legacy rows and the migration could
--      never apply to a live database. NOT VALID still enforces the invariant
--      on every INSERT and UPDATE from here on, which is the invariant that
--      matters; it only declines to re-litigate history. It must never be
--      VALIDATEd while such rows exist.
--   2. `workflow._is_recoverable` is RETAINED. It degrades from a live
--      correctness guard to a legacy-row defence: a checkpoint claiming an
--      `output_hash` it cannot hand back is re-run rather than skipped.

ALTER TABLE extraction_run_steps
    ADD COLUMN output jsonb;

COMMENT ON COLUMN extraction_run_steps.output IS
    'Durable stage result (ADR-0011). Written in the same INSERT as output_hash, '
    'which is the sha256 of its canonical JSON serialisation '
    '(workers: extraction/hashing.py::hash_json over extraction/serialize.py::'
    'serialize_stage_output). NULL on legacy rows written before migration 0006 '
    'and on steps that produced no output.';

-- Both null or both set. NOT VALID for the reason above: pre-0006 rows on
-- terminal runs carry output_hash with no output and can never be repaired.
ALTER TABLE extraction_run_steps
    ADD CONSTRAINT extraction_run_steps_output_pair
    CHECK ((output IS NULL) = (output_hash IS NULL))
    NOT VALID;

-- No-op restatement of 0004's table-level grant; see the header. Kept explicit
-- so a reader adding a column to a column-scoped table (extraction_runs) does
-- not conclude from silence that grants never need touching.
GRANT SELECT, INSERT, UPDATE ON extraction_run_steps TO fel_app;

-- ---------------------------------------------------------------------------
-- Issue #194: an unscored proposal must record "not scored", not a score of 0.
-- ---------------------------------------------------------------------------
-- 0004 declared `record_confidence numeric(4,3) NOT NULL`, so the extraction
-- pipeline — which has no calibrator yet (#62 carries the live scoring work) —
-- persisted `0` for every proposal. `0` is a legitimate value on the CHECK's
-- own scale and reads to a reviewer, and to any consumer sorting a queue by it,
-- as "the extractor is certain this is wrong". NULL is the only spelling of
-- "no score exists" the column can carry.
--
-- The range CHECK is untouched and still binds every non-NULL value; a NULL
-- passes it as unknown, which is the intended semantics.
ALTER TABLE extraction_proposals
    ALTER COLUMN record_confidence DROP NOT NULL;

COMMENT ON COLUMN extraction_proposals.record_confidence IS
    'Calibrated record-level confidence in [0,1], or NULL when no calibrator '
    'scored the proposal (issue #194; live scoring lands with #62). NULL means '
    '"not scored" and is not comparable with 0.';
