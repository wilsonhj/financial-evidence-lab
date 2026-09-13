# Extraction Review Acceptance Proofs Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement each bounded test proof after the reviewed registration merges.

**Goal:** Demonstrate the remaining #61 concurrency, tenant/action and SSE lifecycle acceptance behavior against real isolated PostgreSQL.

**Architecture:** Add three test files using the existing mounted API, fixtures, production transactions and real local streaming socket. Preserve all production code and current contracts; report any reproducible behavior failure to the integration lead before proposing a repair.

**Tech Stack:** Existing pytest, psycopg, httpx and Uvicorn with the frozen Python environment; no dependency or configuration changes.

**Spec:** Canonical specs/001-financial-evidence-lab/spec.md; accepted ADR-0024 and docs/superpowers/plans/2026-09-11-extraction-review-backend.md. Issue #61 owns this acceptance follow-up; the historical evidence map below is subordinate to those requirements.

## Dispatch and verification

Branch `agent/61-acceptance-proofs` starts from merged PR299 (`19e5b9ac1ccbcf1b8ca8901ef8d4bd67d52ba79a`) or a descendant after reviewed control registration. Exactly the three files in the minimum test lane below are writable. Use a dedicated lead-authorized local database and its existing fixture helper database; never use a benchmark, another lane or hosted database.

- [ ] Add and run the same-head correction proof, including different-key precondition failure and same-key exact receipt replay.
- [ ] Add and run actual foreign-tenant resource and denied-action tests against the accepted owner/editor/reviewer/viewer matrix; use valid bodies and real targets so parsing or missing fixtures cannot explain a denial.
- [ ] Add and run real socket/PG stream lifecycle proofs. Synchronize with observable events and bounded waits; assert a timed-out wait rather than silently falling through.
- [ ] If a proof fails, preserve the failure and identify whether setup or product behavior is responsible. Test-only dispatch does not authorize weakening an assertion or changing production behavior.
- [ ] Run focused tests with TEST_DATABASE_URL and FEL_REQUIRE_DB=1, changed-file lint/format/types, required full CI and HTTP/worker/browser acceptance. Report skips separately.
- [ ] Obtain independent exact-head review and lead approval before merge. Preserve issue #61 and reference-profile uncertainty until the lead completes its criterion audit; do not mark canonical tasks.

The map below was written before PR299 merged. That merge and its final CI are now verified above; all other limits remain applicable.

---

# Issue61 acceptance audit — September13

Read-only assessment against issue61's current GitHub body, canonical spec, accepted ADR0024/backend plan, merged290/291/294/295/297, approved299 and measured benchmark. This is an evidence map, not a closure decision or a new gate. No repository changes or new executions were made for this audit. Root owns closure/canonical checkboxes.

## Criterion map

| Criterion | Verified evidence | Remaining before an unqualified issue61 acceptance claim |
|---|---|---|
| Generated0.9 contract, mounted run/proposal/history/correction operations, bounded pages/closed errors |290 production mount/marker integration, contract parity and combined CI; generated web consumers;291/294/297 reviewed web fixes |299 final rebased CI/merge remains pending at audit time. No new schema or hand-written TS model is needed. |
| Deterministic revalidation, exact source bytes, explicit conflicts and unchanged unselected dispositions |API revalidation/conflict/edit-merge/current-head tests;295 unrelated-invalid peer boundaries and per-group provenance; immutable original fields; existing worker validators unchanged |No additional confirmed source defect found in this bounded audit.299 rejects six proven malformed command representations before writes. |
| Atomic batch expected versions, receipts and concurrency |`test_review_concurrency.py:19` uses two real competing transactions and observed PG blocking; same key exact replay, different keys one200/one412. Correction history/replay/stale412 are covered by `test_corrections.py:10`. |**Same-head concurrent correction proof missing.** `test_current_approved_peers.py:234` corrects two different logical records and expects201/422; it does not prove issue61's same-head one201/one412 condition. Fixture/browser sequential stale actions are not this proof. |
| Tenant-hidden404 and role-authorized actions |Shared authentication resolves membership from DB; extraction permissions tests prove forged owner claims do not change actual capabilities. Production SQL/RLS is tenant-qualified. |**Extraction endpoint negative matrix missing.** `test_reads.py:62` creates another workspace in the same org and tests a nonexistent run UUID. `test_permissions.py:31` tests capability projection, not every forbidden mutation. Generic `test_tenancy.py` exercises workspace endpoints, not actual foreign extraction resources. Need real second-tenant IDs and forbidden action requests with valid bodies. |
| Resumable bounded SSE, live review completion and accessible consumer |`test_sse.py:41` proves later committed events while open and terminal replay. `test_events.py` validates unsafe resume IDs and bounded history. Committed cross-stack acceptance opens stream before real queue/worker production, reviews via browser and inspects immutable correction/history. |**Live lifecycle negative proofs missing:** membership revocation during a stream; disconnect with no retained checkout/transaction; a valid event ID belonging to another run; oversized stored payload/frame failure. Published backend plan slices1/9 explicitly require these. Source checks exist, so test first without assuming a defect. |
| Keyboard graph/table, visible source/confidence/validation/conflict/history, safe drafts and navigation |24 fixture Chromium tests plus production HTTP/queue/Next/Chromium acceptance;291 terminal-selection/comparison repair,294 standalone patch parsing,297 stale-lock/winner-pruning fixes |Preserve these final-head required CI checks. This bounded audit did not rerun an independent accessibility study or claim full hosted UI coverage. |
| Local extraction latency targets |At exact e6e24b0:1 preflight+10 warmups+100 sequential measured cycles, no failures/retries. p95 create12.451541ms;100-item review550.613459ms; waiting reconnect16.744875ms; terminal12.971ms. Independently verified raw rows/hash/math and842 archived source files. |**Does not establish canonical reference-profile performance.** See distinction below. No extrapolation to299 or25 concurrent users. |

The earlier proposed correction discovery race is **not a blocking residual**: run/v1 rejects cross-run members; approval resolves attached open groups; resolved groups reject additions. No current writer-reachable failure was reproduced. Do not introduce a synthetic impossible setup merely to justify a lock change.

## Minimum next acceptance-test lane

New branch after299 merges, test ownership only unless a concrete RED proof demonstrates a source defect. Reuse current real-byte/mock-worker fixtures and a dedicated approved test DB. No shared fixture/global config/dependency changes.

1. `apps/api/tests/extraction/test_correction_concurrency.py`: create a real approved record; capture one immutable head/ETag; pause the first current correction after its real run lock using the existing `_locked_rows` seam; start a second request with the same ETag and a different key. Observe `pg_blocking_pids` on the second connection before release, bound every wait. Require statuses201/412, exactly one appended version/head advance, unchanged previous version/evidence and no failed-success receipt. Same-key variant requires byte-identical201 body/ETag/Location and one version/audit/receipt, matching existing exact-replay requirement.

2. `apps/api/tests/extraction/test_access_boundaries.py`: create ownerA's actual run/proposal/conflict/approved version and ownerB's own organization/membership/workspace. B is a legitimate member, not a forged/nonmember token. Parameterize the frozen endpoint inventory: A-scoped lists/detail/history/events and valid mutation targets return indistinguishable404 forB and create no cross-org state/receipt. Confirm B's own workspace is accessible as a positive control. Parameterize denied actions with valid source/command/precondition bodies: viewer create/cancel/rerun/accept/edit/reject/merge/correct all403; reviewer create/cancel/rerun403; forged owner claim cannot override each DB role. Keep the current all-role read allowance. Do not weaken403/404 distinctions by accepting arbitrary error sets.

3. `apps/api/tests/extraction/test_sse_lifecycle.py`: real local HTTP socket against current route; drain initial authorized batch and establish waiting_review before the negative action. Remove membership (owner→viewer alone is **not revocation**, because viewers may read); commit a later event and require no new event payload reaches that revoked client, with bounded stream termination. Use a valid other-run/other-tenant event ID for resume and require initial404. Disconnect a live waiting stream and verify its DB checkout/transaction is released, with no worker thread/connection leak and subsequent authorized requests succeeding. Inspect actual pool/PG state, not only a mocked close method. An oversized persisted payload should fail explicitly (413 before streaming for an initial oversized event), never truncate/skip it or expose content. Keep invalid safe-integer tests already present. A heartbeat check may use a controlled monotonic clock seam while keeping real socket/PG; do not wait minutes or alter production intervals.

Keep meaningful same-run/member serialization tests already passing. Bound fixtures and waits; don't rewrite existing assertions to make new results pass. These are concrete missing acceptance proofs, not authorization for speculative source changes.

## Reference-profile distinction and owner decisions

- Canonical `specs/001-financial-evidence-lab/spec.md:864` states p95 with **25 concurrent active users**,100 issuers/eight years/10million passages/15million embeddings, API+worker8vCPU/32GiB and DB8vCPU/32GiB; client50Mbps/50msRTT. CI may use proportionally scaled fixtures; release-candidate tests use the full reference profile.
- Subordinate `specs/003-agentic-extraction/spec.md:178` adds extraction create<500ms,100-item review<1s, missed-event reconnect<2s in the reference environment. Backend plan line171 asks for the accepted mock reference measurements; it does not amend canonical concurrency or grant hosted execution.
- Current benchmark is one sequential client, local Mac12CPU/24GiB+localPG,6208 source bytes, conflict-free rows. It proves only those documented local measurements. The committed record explicitly excludes hosted/network/browser/model/worst-case costs and pins its backend commit.
- Minimum additional feature-load evidence would preserve25 active users against an explicitly documented scaled mock fixture and report per-operation p95/errors/full samples. It would still not replace full release-profile acceptance. Do not reduce concurrency, silently treat110sequential preparatory/measured cycles as concurrent users, or claim the full corpus/hardware/network profile was exercised.
- Lead must determine the appropriate recorded boundary for issue61 closure versus separate release acceptance ownership, without altering gates. Until then keep reference-profile status explicitly unproven. No new hosted/SEC/provider request is authorized by this audit.

## Outside issue61's implementation ownership

Issue61 explicitly targets T0308–T0309 and says no credentials. Calibration/scoring/evaluation and broader M3 completion are separately owned (#62/T0306/T0307/T0310). The M3§7 live OpenAI smoke and accuracy gates remain held/outstanding; neither local mock success nor closing a review implementation issue can claim those milestone gates. Do not treat source/v3 NULL confidence as a new calibration algorithm. Canonical checkboxes currently remain lead-owned and unchecked.
