# Extraction event commit ordering implementation plan

> Implement only after lead ownership registration merges. Use the executing-plans skill; no delegation is required. This is the separate EXTRACTION-EVENT-ORDERING prerequisite under #135, not an expansion of PR280.

**Goal:** Make numeric extraction event replay complete when current PostgreSQL stores write concurrently for the same run.

**Architecture:** Serialize event-containing transactions on their extraction run before any child write or event identity allocation. Retain the existing numeric identity, metadata projection, child guards, checkpoint atomicity and API run-first lock order.

**Spec:** Accepted extraction review plan, ADR0024, extraction-event/v1 and M3 data-model event identity guarantee. Investigated against PR280 implementation a7ad7ac plus permissions delta 0bb237b. Root has registered this bounded dispatch in the pending wave9 control PR282.

## Exact ownership

- `workers/src/fel_workers/extraction/persist_events.py`
- `workers/src/fel_workers/extraction/persist_checkpoint.py`
- `workers/src/fel_workers/extraction/persist.py`
- `workers/tests/extraction/test_event_commit_order.py` (new)

No reader/API changes, migrations, sequence changes, contract changes, financial algorithm/hash/version changes, dependency changes, workflow restructuring or existing golden/test edits. Root owns control records and merges.

## Concrete defect and evidence

`db/migrations/0004_extraction_core.sql:461–473` implements `fel_assert_extraction_run_open` using run `FOR SHARE`. The event child trigger calls this after PostgreSQL has allocated the event identity. Two compatible SHARE locks therefore do not order commits by identity.

Current production paths:

1. `persist_events.py:23`: `PostgresEventStore.append` executes its INSERT directly on the production autocommit connection.
2. `persist_checkpoint.py:252–304`: `commit_succeeded_atomic` starts a transaction at line289, inserts a checkpoint child (taking SHARE), then calls append before committing.
3. `persist.py:324–384`: `persist_outputs_atomic` starts a transaction at line364, writes proposals/evidence/conflicts, then appends `proposals_persisted` before committing. Group acquisition can already occur before append.
4. `workflow.py:90`, `:277`, `:329`: workflow start and step start events, plus the application commit fence before the checkpoint transaction. The lease check does not hold the queue lease row locked across the later durable transaction. A paused old writer after that check can overlap a subsequent current-store append. Checkpoint uniqueness protects successful checkpoint identity; it does not serialize other event types.

A disposable migrated database and two actual current stores reproduced this (the probe database was removed afterward; no repository edits):

```text
visible_before_old_commit: [(2, 'run_started')]
all_after_commit: [(1, 'step_completed'), (2, 'run_started')]
resume_after_observed_id: []
late_lower_id_skipped: True
```

The test-only pause is after actual `PostgresEventStore.append` INSERT inside the actual checkpoint transaction, before its commit. It models process scheduling at an existing boundary, not a fake alternate event writer. This is a store-level proof; it does not claim to exercise a complete queue lease takeover. The reviewer independently reproduced SHARE-to-NO KEY UPDATE upgrade deadlock (40P01) and verified that acquiring NO KEY UPDATE first blocks the second writer before allocation.

## Minimal locking change

Use an explicit transaction and `SELECT id FROM extraction_runs WHERE id=%s AND org_id=%s FOR NO KEY UPDATE`. The weaker-than-UPDATE lock is sufficient: it conflicts with another NO KEY UPDATE, existing SHARE and API FOR UPDATE, while not unnecessarily excluding KEY SHARE FK checks. Retain the existing trigger's terminal/error checks; the new helper orders writes, it does not replace authorization or classify errors.

- Define one private run-lock helper in `persist_events.py`; the two atomic stores import it. This leaf imports only existing event definitions/psycopg, so no import cycle or new framework is needed.
- In standalone `append`, open `conn.transaction()`, acquire the run lock, then perform INSERT. A nested call participates in the caller's transaction/savepoint and must retain the parent lock until its outer commit.
- At the beginning of `commit_succeeded_atomic`'s existing transaction, acquire the run lock **before `_insert_step_row`**.
- At the beginning of `persist_outputs_atomic`'s existing transaction, acquire the run lock **before `persist_proposals`**, evidence writes or conflict locks.
- Preserve append's public return/memory semantics and existing payload redaction. Consumers serving SSE use actual table IDs, not the memory store's local event counter.
- Never put only a late lock inside append: both outer transactions may already hold SHARE and deadlock upgrading. Never add an advisory event lock: ordering it against API run locks introduces another lock class and possible inversion. A trigger alone is too late for identity allocation and child-first callers.
- No lock spans a provider call, evidence fetching or workflow execution. These are bounded persistence transactions only. Different runs remain independent. New API writers must acquire all affected runs in sorted UUID order before groups/proposals/heads and append before terminal status, as ADR0024 already requires.
- Audit all production callers of these stores before implementation. The current handler uses autocommit connections and these two event-containing outer transactions. Arbitrary external callers that first write children in a custom outer transaction must obey the same run-first rule; do not claim a database-wide guarantee for uncoordinated direct SQL. Standalone step-only methods need no later upgrade because their production writes finish before standalone event transactions. If an actual additional production outer transaction is found, request its exact path before editing.
- PostgreSQL's existing identity sequence uses default CACHE1; retain it. Do not claim this proof for a deployment that independently changes sequence cache behavior.

## Test-first sequence

1. Add a current-store regression using two independent autocommit PostgreSQL connections and explicit threading events. Pause A after its real checkpoint event INSERT; start B's real standalone append. On the old implementation, B commits and the observed resume query permanently skips A's lower ID. Verify RED for this actual assertion before production edits.
2. Implement the three entry-point changes above. Prove B is observably blocked with PostgreSQL lock/wait inspection and bounded deadlines, not a timing-only sleep. Release A; both commit. Assert ordered rows and concatenated bounded `id > last_seen` reads contain every event exactly once.
3. Parameterize the first writer as `persist_outputs_atomic` with real proposals/evidence/conflicts, then `commit_succeeded_atomic`; include standalone-versus-standalone. The output test must show locking occurs before child/group writes, not merely pass the checkpoint case.
4. Add rollback: A allocates then rolls back; B completes without blocked residue, committed events remain replayable despite legal sequence gaps. Add different-run progress to prove no accidental global serialization.
5. Exercise a competing API-shaped run-FOR-UPDATE transaction using SQL in this new worker test: run-first acquisition, event append and permitted state update; show completion without lock inversion. Preserve existing checkpoint repair, stale lease and terminal no-mutation tests unchanged.
6. Run focused tests, full PostgreSQL extraction suite and existing golden/ontology tests. Check ruff, black and mypy; then full required CI with independent review. Record actual commands, test counts and commit SHA in the draft PR. Do not lower coverage floors.

Commands from the registered implementation checkout, with its own migrated test database configured and the existing locked environment:

```sh
export FEL_REQUIRE_DB=1
: "${TEST_DATABASE_URL:?Set the dedicated local test database URL before running tests}"
/private/tmp/fel203-dev/bin/pytest workers/tests/extraction/test_event_commit_order.py -q
/private/tmp/fel203-dev/bin/pytest workers/tests/extraction -q
/private/tmp/fel203-dev/bin/ruff check workers/src/fel_workers/extraction/persist.py workers/src/fel_workers/extraction/persist_events.py workers/src/fel_workers/extraction/persist_checkpoint.py workers/tests/extraction/test_event_commit_order.py
/private/tmp/fel203-dev/bin/black --check workers/src/fel_workers/extraction/persist.py workers/src/fel_workers/extraction/persist_events.py workers/src/fel_workers/extraction/persist_checkpoint.py workers/tests/extraction/test_event_commit_order.py
/private/tmp/fel203-dev/bin/mypy workers/src
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH make ci PY=/private/tmp/fel203-dev/bin
```

## Reproduction core

No separate scratch script was saved; the original probe ran inline. This equivalent core uses the same real store pause. The caller creates a uniquely named disposable database, applies current migrations, invokes existing `_seed_parents`, `_request(str(uuid.uuid4()))`, `_seed_run`, and supplies three autocommit connections plus that request. Never run the seeding against another lane's database. The original probe cleaned only its own disposable database.

```python
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from fel_workers.extraction.hashing import hash_json
from fel_workers.extraction.persist_checkpoint import PostgresCheckpointStore
from fel_workers.extraction.persist_events import PostgresEventStore
from fel_workers.extraction.types import StageRecord

def reproduce(old, new, reader, request):
    inserted, release = Event(), Event()

    class PausedEvents(PostgresEventStore):
        def append(self, **kwargs):
            event = super().append(**kwargs)
            inserted.set()
            assert release.wait(10), 'bounded probe release timed out'
            return event

    output = {'probe': 'metadata'}
    record = StageRecord(step_name='validate_request', attempt=1,
                         status='succeeded', input_hash=hash_json({'probe': 1}),
                         output_hash=hash_json(output), output=output)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            PostgresCheckpointStore(old).commit_succeeded_atomic,
            run_id=request.run_id, org_id=request.org_id,
            workflow_version=request.workflow_version, record=record,
            events=PausedEvents(old), event_payload={'step': 'validate_request'})
        try:
            assert inserted.wait(5)
            PostgresEventStore(new).append(
                run_id=request.run_id, org_id=request.org_id,
                event_type='run_started',
                payload={'workflow_version': request.workflow_version})
            visible = reader.execute(
                'SELECT id,event_type FROM extraction_run_events '
                'WHERE run_id=%s ORDER BY id', (request.run_id,)).fetchall()
        finally:
            release.set()
        first.result(timeout=5)
    after = reader.execute(
        'SELECT id,event_type FROM extraction_run_events '
        'WHERE run_id=%s ORDER BY id', (request.run_id,)).fetchall()
    resumed = reader.execute(
        'SELECT id,event_type FROM extraction_run_events '
        'WHERE run_id=%s AND id>%s ORDER BY id',
        (request.run_id, visible[-1][0])).fetchall()
    return visible, after, resumed
```

That diagnostic is intentionally for the old implementation: B will block after the fix, so the GREEN regression must launch B concurrently, observe its blocking and release A before awaiting B. Do not mistake the diagnostic's release timeout for a fixed-code failure.

## Limits and deployment

This fixes same-run event visibility/replay order. It does not strengthen ownership fencing or make the currently separate worker terminal event/status statements atomic. Preserve those existing behaviors and report them separately; no claim of lifecycle/lease correctness follows from this ordering proof. During deployment, old unordered writers must be drained before enabling a consumer that relies on the guarantee. No hosted rollout is authorized here. Backend's live SSE readiness is gated on this reviewed prerequisite; the registered backend/web implementation dispatch waits for its merge. Read-only planning may continue on disjoint files.
