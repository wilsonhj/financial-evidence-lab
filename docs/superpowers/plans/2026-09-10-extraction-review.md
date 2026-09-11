# #61 / #135: ratified implementation design

Date: 2026-09-10. Baseline: PR #272 (`fa4cfa2`), followed by execution-control PR #277 (`bbf0be2`). Prerequisite issue #278 owns ADR-0024, OpenAPI/package 0.8.0, migration 0011 and the compatible conflict store on branch `agent/278-extraction-review-contract`. The integration lead approved this design under the owner's instruction to implement the backlog. Backend/web #61 work starts after the reviewed contract prerequisite merges. No hosted rollout is authorized or certified here.

The canonical parent spec/plan/task ledger remains `specs/001-financial-evidence-lab/`. Accepted M3 behavior comes from `specs/003-agentic-extraction/{spec,data-model}.md`, the extraction API contract, current worker source and ADR0022. Do not copy or mark task-ledger entries here.

## Outcome and fixed scope

Ship authenticated extraction run/proposal/history APIs; atomic accept/edit/reject/merge/bulk review; immutable approved versions and corrections; exact idempotent replay and optimistic concurrency; bounded reads; accessible review UI; and a mounted same-origin live SSE proxy/consumer. #135 is delivered within the #61 web lane. All execution uses existing mocks. OpenAI/provider integration, credentials, paid calls and scoring/calibration are held out of scope.

Owners/editors create, cancel and rerun; owners/editors/reviewers review and correct; all four roles read. Existing RLS and actual membership resolution govern every request. All new acceptance revalidates actual canonical bytes and current deterministic rules. Invalid financial, unit, range, accounting, citation or temporal evidence cannot be overridden with a reason. Historical runs, payloads, approval versions, financial hashes and v3/v2/v3 workflow/normalizer/validator pins remain unchanged.

The lead has selected these implementation decisions:

- Run ETag is an opaque digest of the complete deterministic run representation. No run-version trigger.
- New extraction endpoints store a versioned internal receipt envelope in existing `idempotency_keys.response_body`; no receipt columns/table.
- Correction writes an immutable child version, audit and receipt; no expansion of `extraction_reviews.action`.
- Add a small `extraction_runs.cancel_requested_at` column for coherent cancellation acknowledgement.
- Add immutable nullable `approved_extraction_versions.validation_context` for approval-time policy/source provenance; old versions remain NULL.
- Explicit group adjudication names complete current membership and selected winners; unselected states remain unchanged. Later contradictory acceptance is blocked; an explicit edit eliminating the contradiction is revalidated against the recorded winner.
- Successful reruns after adjudication use opt-in per-run conflict occurrences, preserving legacy NULL occurrences and unchanged financial comparison hashes.
- Existing artifacts keep their frozen cutoff. New creation/rerun applies min(current workspace cutoff, requested/parent cutoff); never silently drops an ineligible source.

## Control change: exact scope and contract inventory

The integration lead assigns the #278 owner these shared paths through the control registration. Backend/web implementation does not edit them independently. No hosted rollout is authorized or performed; rollout instructions are future deployment gates.

Existing files to change:

- `docs/decisions/ADR-0024-extraction-review-and-conflict-occurrences.md` (new accepted decision published by lead).
- `packages/contracts/openapi/openapi.yaml` (0.8.0 extraction routes/components only; #191 retrieval/reader behavior unchanged).
- `packages/contracts/package.json`, `packages/contracts/src/index.ts` (version and schema registry), `packages/contracts/src/generated/api.ts` (generated only), `packages/contracts/contracts.test.ts` (version assertion and registry/fixture integration), `packages/contracts/README.md` (new contract inventory).
- `specs/003-agentic-extraction/contracts/extraction-api.yaml` (align the extraction-only reference contract with the accepted root contract; no financial payload schema copy/edit).
- `db/migrations/0011_extraction_review.sql` (new), `db/migrations/tests/0011_extraction_review.test.sql` (new), `db/migrations/README.md`.
- `docs/handoff/workstreams.yaml`, `docs/handoff/CONTRACTS.md`, and a published `docs/superpowers/plans/2026-09-10-extraction-review.md` (lead dispatch/evidence only; no duplicate task ledger).

New standalone JSON schemas and one mandatory valid fixture each:

| Schema under `packages/contracts/schemas/` | Matching `packages/contracts/fixtures/` | Purpose |
| --- | --- | --- |
| `extraction-review-command.schema.json` | `extraction-review-command.json` | Closed action-specific review replacement and adjudication inputs. |
| `extraction-review-result.schema.json` | `extraction-review-result.json` | Stable result IDs, states, versions and ETags used by receipts/UI. |
| `extraction-conflict.schema.json` | `extraction-conflict.json` | Membership, occurrence, resolution and precondition read model. |
| `extraction-validation-context.schema.json` | `extraction-validation-context.json` | Immutable acceptance-policy and source-pin provenance. |
| `extraction-event-page.schema.json` | `extraction-event-page.json` | Bounded stored event history, referencing extraction-event/v1. |

Each new schema gets its own `/v1` $id and x-fel-version1.0.0. OpenAPI references these schemas rather than maintaining manual mirrors. Existing `extraction-payload.schema.json`, `extraction-event.schema.json`, their existing fixtures and subordinate financial payload schemas stay byte-identical. Existing `CorrectionCommand` continues referencing extraction-payload/v1 and EvidenceEdge; only its explicit audit/replay/ETag and revalidation semantics need documentation, not a second replacement payload schema.

New `packages/contracts/extraction-review.test.ts` validates the above schemas and OpenAPI generation/type references. Add named fixtures `extraction-review-cases.valid.json` and `extraction-review-cases.invalid.json` containing the accepted action variants and rejected malformed commands; these are explicit test datasets, not extra automatically discovered schema pairs. Include accept/reject/edit/merge, no-winner resolution accompanying final rejection, stale/missing membership preconditions, extra version keys, unknown fields, invalid decimal type, mixed edit selection, oversized batch, nullable uncalibrated output, parent/new approval versions, cancellation acknowledgement and occurrence isolation. Runtime-only equality/state/financial checks are tested in API/worker tests, not pretended to be JSON Schema guarantees.

## Contract decisions and field traceability

| Surface | Concrete contract | Accepted requirement |
| --- | --- | --- |
| Run create/detail/cancel/rerun | Existing paths and generated run union; add nullable cancel_requested_at to run output and ETag on every run mutation response. Detail ETag hashes the complete deterministic response, including status/usage/cancellation. Preserve integer version as recorded metadata, not concurrency token. | M3-WF-001/006, US1, existing cancel If-Match and 200 “Cancel requested” response. |
| Run source selection | Complete sorted span/claim IDs, document versions, corpus, cutoff and occurrence policy in immutable text-free input_manifest; canonical input_hash unchanged algorithm. `conflict_occurrence_policy: "run/v1"` is the new opt-in manifest key; absent means legacy semantics. It is set by the producer, never accepted as an arbitrary client override. | Frozen run pins and rerun without mutating old proposals, M3-REV-003. |
| ReviewCommand | Closed action discriminator; selected extraction_ids max100; exact expected_versions; reason1–2000. Accept/reject carry no patch. Edit patch is a list of `{extraction_id,payload,evidence}` with exactly one entry for each selected ID. Merge patch is `{payload_source_id}` naming one selected input; no invented arithmetic or additional free-form patch. | M3-REV-004/005/006; atomic bulk, typed financial payload, immutable source proposals. |
| Explicit adjudication | Optional conflict_resolution is an array of `{conflict_id,expected_etag,member_versions,selected_winner_ids,reason}`. member_versions represents the complete observed membership; selected_winner_ids is a subset of explicitly selected proposals. For merge these IDs identify selected inputs whose single resulting approved record wins. Empty winners allowed only when this transaction leaves every member rejected/superseded. Require all relevant overlapping groups explicitly resolved. | US2 conflict blocking; US4 visible alternatives; reason required for conflict override. |
| ReviewResult | Existing review_id/action/proposal_states/approved_record_ids plus proposal_versions, immutable approved version IDs with head ETags, and resolved group IDs/ETags. Results describe this commit and are replayed unchanged even after later head changes. | Atomic optimistic review and reconstructible immutable history. |
| Proposal output | record_confidence nullable; NULL renders “Uncalibrated.” Preserve recorded priority/field confidences. Deterministic validation projection exposes actual blocker codes/details; do not fabricate pass/calibration results. Expose conflict links so every blocker is actionable. | Review confidence/validation/conflict visibility; current source v3 and #194 behavior. |
| Conflict output | id, base conflict_key, occurrence_run_id nullable, state/reasons, complete bounded member IDs+versions, ETag, recorded selected winner/result IDs and reason/actor/time from immutable review plus group resolution. No implicit loser disposition. | Explicit adjudication and stale membership prevention. |
| Approved detail/history/correction | Detail returns ETag. History is Page with immutable version links; add `GET /v1/approved-extractions/{recordId}/versions/{versionId}`. Include parent ID, approval_reason, stored normalizer/validator versions and nullable validation_context. Correction returns the newly appended immutable version and new head ETag. | US3 reconstructible state and M3-REV-007/008. |
| Validation context | `{schema_version:"extraction-validation-context/v1",workflow_version,normalizer_version,validator_version,unit_policy_version,range_policy_version,source_runs:[{run_id,as_of,corpus_version_id,ontology_version,workflow_version,policy_id}]}`. Deduplicate/sort source_runs; new versions require complete context. Approval ontology stays existing ontology_version. Corrections inherit source pins and record current validation versions. | Reproducible immutable provenance, existing source and current acceptance policies. |
| Bounded lists and steps | Existing run/proposal lists become explicit Page; approved versions Page; add run step summaries, conflict list/detail, stored event-history routes below. Scope cursors to endpoint/org/resource/cutoff/corpus/filter; use #191 codec extension. | M3-API-004 and execution/history visibility. |
| SSE | Existing extraction-event/v1 endpoint, typed Last-Event-ID, metadata-only events, 15–30s heartbeat, bounded replay and client retention; wait-for-review remains nonterminal. | M3-API-003, #135 actual live stream. |

New read paths: `GET /v1/extraction-runs/{runId}/steps`, `GET /v1/extraction-runs/{runId}/event-history`, `GET /v1/workspaces/{workspaceId}/extraction-conflicts`, `GET /v1/extraction-conflicts/{conflictId}` and approved immutable version detail above. Steps expose stage/attempt/status/timestamps/usage/hash/redacted errors only, never checkpoint output. Detail conflict membership is bounded and complete; an oversized group is an explicit blocker, never a partial membership presented as complete. Lists default50/max200; selected review batch max100; selected source IDs max200; request body max1MiB; evidence bundle max8MiB with existing reader per-object caps; SSE fetch batch200/frame64KiB/client retained500. These finite implementation caps support existing bounded-work requirements; oversized inputs fail with safe resource IDs and closed errors. No automatic all-page draining.

Closed error codes distinguish malformed request/cursor, wrong scope, key reused with different request, stale proposal/head/group (412), terminal-state action, blocked validation, incompatible merge (409), evidence integrity/cutoff failure, unavailable historical validation policy and oversized resource (413). Use the existing error/v1 envelope and safe details; RLS-hidden objects remain indistinguishable404. Do not return raw evidence, backend exception text or provider output in errors.

## Minimal migration0011 and rollout

1. Add nullable `extraction_runs.cancel_requested_at timestamptz`; grant fel_app UPDATE on this column only in addition to existing grants. Terminal/pin guards continue to apply. No version trigger or pin rewrite.
2. Add nullable `approved_extraction_versions.validation_context jsonb`; insert is already allowed, update/delete remain forbidden. No backfill of unprovable history. Validate new context shape in API; preserve original evidence_manifest and its hash format.
3. Add nullable `extraction_conflicts.occurrence_run_id uuid`, same-tenant/workspace FK to extraction_runs. Replace unique(org_id,workspace_id,conflict_key) with unique(org_id,workspace_id,conflict_key,occurrence_run_id) NULLS NOT DISTINCT. Existing rows stay NULL; do not transform keys or decisions. Extend the existing conflict guard’s explicit immutable-field list with occurrence_run_id; a new column is not automatically protected by that trigger. Once resolved/superseded, forbid status reopening or any change to resolution actor/time/note and immutable identity; no-op updates may remain no-ops. No new financial comparison key or rewrite of historical adjudication.
4. Add a BEFORE INSERT conflict-member guard used by worker and API roles. For a new member, resolve its immutable run ID and acquire/assert the run lock before locking its group, matching review's run-before-group order. An exactly matching already-existing (conflict_id,proposal_id,org_id) tuple must RETURN NEW so PostgreSQL’s existing ON CONFLICT DO NOTHING can preserve legacy retry semantics, even when its group subsequently became terminal; this adds no membership or authority. For a genuinely new member, recheck open group status, enforce matching tenant/workspace and (when non-NULL) proposal.run_id == occurrence_run_id, and apply existing open-run protection. A mismatched org or altered tuple must never use the duplicate bypass. A row-lock/digest in API alone is insufficient: current worker checks group status before a later INSERT. This guard closes that race. Preserve existing append-only behavior and least-privilege grants.
5. Add only indexes justified by bounded new read SQL/EXPLAIN: no broad cleanup. Existing run/workspace, proposal/run, approved-version/record and event indexes are the starting point; record an added index only if the selected filter/order needs it.

No receipt table/columns, correction action CHECK change, confidence/calibrator schema change, old numbered migration edit or canonical-record unique index.

**Coordinated rollout is required:** old extraction workers use three-column ON CONFLICT and cannot run after the unique constraint replacement. Drain/stop old extraction workers, apply0011 and deploy the compatible worker before enabling new API create/rerun. Run migration/worker readiness tests before starting new jobs. This plan does not claim zero-downtime compatibility. On rollback, stop producers and preserve migrated rows; do not destructively downgrade data to restore the old uniqueness rule.

## Bounded worker portion of prerequisite #278

Owner: the same #278 prerequisite owner as contract/migration, separate from backend and web. Contract, migration and compatible worker ship together in one PR. Allowed production paths only `workers/src/fel_workers/extraction/persist.py` and new `workers/src/fel_workers/extraction/persist_conflicts.py`; tests only new `workers/tests/extraction/test_conflict_occurrences.py` plus narrowly relevant existing persistence integration tests if their old SQL constraint assumption changes. Existing workflow/stage/type/normalizer/validator/hash/namespace functions and fixtures remain untouched.

Move only the bounded conflict-write body into the new leaf if needed to keep persist.py <=500 lines, retaining the old method/signature/import seams. Resolve member proposal run IDs from authoritative rows in the same tenant/workspace; a new opted-in group must have exactly one run. Read that run's immutable input_manifest and derive occurrence_run_id when `conflict_occurrence_policy == "run/v1"`; only an absent key in a valid object manifest retains NULL legacy behavior. A present null/non-string/unknown policy or malformed manifest fails closed; never treat malformed opt-in as absence. Read every relevant member/run and reject missing rows or inconsistent policies rather than silently selecting a subset. SQL upsert always uses the new four-column constraint and NULL-safe lookup. Legacy NULL keys retain their current semantics; opted-in retry reuses its run occurrence, while a child run receives an independent open group with the unchanged financial conflict_key. Never inherit resolved_by/status/winners from another run.

`persist_outputs_atomic` remains the transaction boundary for proposals+evidence+conflicts+events; terminal and lease fences remain unchanged. DB member insertion guard locks/rechecks group state even if the earlier worker status read raced with review. Occurrence lookup is persistence identity, not a change to `validate/duplicates.py:conflict_key_for`, unit/range policy, proposal ID or the workflow state-hash algorithm. No workflow version bump is needed: new runs explicitly bind the named persistence policy in the immutable input_manifest and its canonical input_hash; handler pin binding rejects a job that contradicts that row, and persistence derives the occurrence from those authoritative rows. The same v3 finite stages and financial algorithms execute; historical rows without the policy retain their prior behavior and hashes. New manifests naturally have their own new input hashes, not rewritten historical hashes.

Tests: legacy NULL row/key/history unchanged; old run resume still legacy; new child of resolved parent produces a new open occurrence; repeated same-run persistence creates no duplicate; two concurrent workers converge; member run/tenant/workspace mismatch blocked; resolved-group new insertion race blocked; exact legacy duplicate insert retains ON CONFLICT no-op; changed occurrence/resolution actor/time/note and reopening denied; unknown/null/non-string policy fails closed; atomic stage failure leaves no orphan proposals. Full current extraction, ontology and golden tests pass unchanged. This worker portion and its migration/contract must merge together after independent review before backend/web dispatch.

## Backend module ownership and behavior

Allowed new package `apps/api/app/extraction/`: `__init__.py`, `models.py`, `serializers.py`, `routes_runs.py`, `routes_review.py`, `routes_history.py`, `routes_events.py`, `runs.py`, `review.py`, `corrections.py`, `conflicts.py`, `evidence.py`, `validation.py`, `receipts.py`, `reads.py`, `events.py`. New tests `apps/api/tests/extraction/**`. Existing production edits only `apps/api/app/main.py` (router mount) and `apps/api/app/pagination.py` (closed additive extraction endpoint/filter/key support); focused pagination tests may extend. New files target100–350 lines and must stay near/below500. Add a named SQL/read leaf only if a concrete module otherwise exceeds that boundary; no generic service framework.

Dependency direction: main -> routers -> services -> read/evidence/validation/receipt/conflict/event leaves -> established app auth/db/errors/reader helpers and pure worker/ontology code. Leaves receive the same transaction and never commit independently. Models do not import services. Worker modules never import API.

Reuse `get_tenant_context/resolve_membership` and tenant_connection with fel_app; never use a worker service-role connection. Reuse existing worker normalize_payload, validate_proposals, citation_status_for, canonical_json/hash_json and ontology. Runtime already installs the worker wheel into API. Read real canonical text with existing reader helpers, retaining their storage containment, byte bounds, section offsets and hash verification; SQL independently proves complete span IDs, pinned document versions/corpus and publication cutoff. Do not mistake stored citation_status or matching span membership for proof of bytes. Do not duplicate financial rules.

### Creation, cancellation, rerun and ETags

Create authorizes workspace/entity, selects existing immutable policy and corpus, resolves every claim/span, computes min(workspace cutoff, request cutoff), checks/clamps budgets under policy/hard limits and inserts run+job+run_queued event+audit+receipt in one transaction. Input manifest contains sorted IDs/version pins and the producer-set occurrence policy, never text. Current handler requires bounded inline evidence bytes in the durable job payload; supply verified canonical slices through that existing envelope, without leaking them into run/review/events/audit/logs. No policy auto-creation or provider fallback. Mock test policy fixtures are part of the test setup.

Run ETag is a quoted digest over the exact complete deterministic response representation. Get uses a consistent snapshot; cancel locks the run and compares the same projection. Every exposed mutable property participates. No clock-dependent fields enter that projection. Return ETag with create/detail/cancel/rerun responses. Existing version field need not be advanced by worker writes.

Cancel queued/running: lock run, compare If-Match, set run and its tenant-bound job cancellation timestamps atomically, append audit and store receipt. Return current status plus cancel_requested_at; worker cooperatively emits terminal cancellation with existing fencing. Waiting_review has no active worker: API appends run_cancelled and transitions to cancelled in the same transaction, preserving untouched proposal states as non-actionable history. New-key terminal cancel returns409; same successful-key retry returns original receipt. No silent bulk rejection.

Rerun creates a new child and opted-in conflict occurrence policy, retaining original source/corpus and applying min(parent cutoff,current workspace cutoff). Fail before enqueue if unchanged selected evidence is no longer eligible; do not silently drop spans or alter the parent. Preserve parent-run/proposal history; use current executable workflow pins for the new run without changing existing pins. Successful post-resolution rerun is a required integration test for this chosen occurrence design.

### Receipts, atomic review, corrections and adjudication

Receipt storage is existing idempotency_keys: response_status plus response_body `{receipt_version:"extraction-receipt/v1",request_hash,response_headers,body}`. Only new extraction endpoint scopes decode this envelope. Hash canonical actor/resource/action/body/preconditions. The same org+scope+key with different request returns409. Serialize concurrent same-key attempts by deterministic transaction advisory lock; inspect receipt after current authorization, before version preconditions. Return stored body/status/ETag/Location even if the resource later changes. Do not expose the envelope or dynamically reconstruct a receipt. Failed transactions leave no success receipt.

Review keys respect extraction_reviews unique(org,key,action), including collisions across workspaces; scope the review endpoint by action and hash the workspace/resource. Sort set-like IDs before canonical hashing, preserve meaningful arrays. No Python randomized hash for locks.

Discover the affected run/group/proposal/head set, then lock runs in UUID order, groups in UUID order, proposals in UUID order, approved heads in UUID order. Re-read complete membership/state/version under locks. If discovery changes the earlier lock set, roll back and restart bounded discovery; do not acquire earlier lock classes late. Bounded retry handles genuine deadlock/serialization failures. Different-key concurrent review of one version yields one commit/one412, with no partial batch. Same-key concurrent retry returns one exact result.

Validate selected payloads and complete relevant comparison/accounting peers, never a truncated dependency page. Preserve `_normalizer_blockers` through normalize/validate and require one typed draft per selected input; unknown kinds cannot disappear. Rehash actual evidence. Record original source pins and current validation context. Unknown historical policy/ontology that cannot safely validate blocks new acceptance while history remains readable.

Apply normalize/v2 unchanged: ADR0022 permits swapping only high < low < 0 after Decimal/common-scale reconciliation; positive or mixed-sign inversions remain blocked. Raw values, signs, units, scale representation and independent blockers remain. No FX, absolute value, inferred metric polarity, magnitude “repair,” or new calculation.

Accept creates approved logical record/version and marks selected proposal accepted. Edit stores full explicit replacement in immutable review.patch, creates approved version and marks selected accepted; original proposal payload/hash stays unchanged. Reject marks selected rejected with reason, no approved version. Merge requires all selected inputs to match exact kind/entity/metric/period/dimensions/definition-comparability/unit/currency; incomplete identity or incompatibility returns409. Copy the explicitly selected payload_source_id payload, union/deduplicate/sort and verify all selected evidence, create a named new surviving logical record/version and mark all selected inputs superseded. No summation or averaging; no implicit existing-head lookup. Correction is the separate existing-head operation.

Explicit group resolution verifies expected_etag and complete member_versions, names selected winners/result and reason, records immutable review decision and resolves that group. Unselected proposal states/versions are unchanged. The resolution cannot waive financial/citation/temporal blockers. Later acceptance of an unchanged contradictory alternative is blocked against the recorded winner. An explicit edit that removes the contradiction is revalidated against that winner and recorded; it does not reopen or rewrite the prior decision. No new superseding-adjudication endpoint. Empty-winner resolution may accompany a final reject/merge disposition only if every member is then rejected/superseded; do not require a separate “resolve only” action. If multiple groups overlap, every relevant group decision must be explicit and compatible.

Append review/audit/approved versions, change selected states/heads, persist receipt and append review_completed/terminal event before terminal status. Complete each affected waiting_review run only after every proposal is terminal and no related group is open. Any error rolls back the entire batch. Correction locks its approved head, verifies If-Match, validates full replacement/evidence against frozen source context and current rules, inserts n+1 with parent n, changes only head pointer/version, appends correction audit and receipt. Prior version cannot UPDATE/DELETE. No correction review action enum.

## Web ownership, UI and live streaming

New paths only: `apps/web/src/lib/extraction/**`, `apps/web/src/components/extraction/**`, `apps/web/src/app/extractions/**`, `apps/web/src/app/extraction-runs/**`, `apps/web/src/app/approved-extractions/**`, `apps/web/src/app/api/extraction/**`, colocated tests and `apps/web/e2e/extraction-review.spec.ts`. Existing `apps/web/src/app/desk/page.tsx` may receive the minimal navigation link to this real review surface. Preserve its existing navigation tests. No Home/reader/observatory production rewrites, new root dependencies, manual TS mirrors or current web ownership retained by the design agent. Every new code file <=500 lines.

Generated types govern both mock and HTTP sources. Explicit mock/http selection remains server-side and fails closed; no provider credential or browser bearer in source URLs, logs, local storage or bundles. Existing production identity limitation is not redesigned here: use the current authenticated API context, and do not present a static development mock token as per-user production auth.

Provide bounded run/queue/history navigation; create/cancel/rerun controls per role; exact source-linked proposal/raw+normalized fields; uncalibrated confidence; actual blockers; complete group context; explicit selected counts/winners; atomic review buttons; immutable version history/correction form. Preserve drafts on412, refresh comparison/version state and require intentional resubmission. Network retries retain the same key/body; an edited command uses a new key. Reader links carry the artifact's immutable cutoff/corpus/document version, not unrelated runtime defaults.

Mount `apps/web/src/app/api/extraction/runs/[runId]/events/route.ts` as the same-origin streaming route; bounded action proxy routes remain under this extraction API subtree. Validate UUID/resume fields and forward only the configured upstream route. Mutating proxies enforce intended method/JSON body and same-origin request checks; API still authorizes role. Abort upstream on disconnect, use no-store, avoid buffering, honor backpressure. Never expose arbitrary URL forwarding.

Adapt the existing tested Observatory framing/reconnect design into extraction-specific generated event validation without weakening retrieval-event parsing. SSE validates extraction-event/v1 and run identity, resumes strictly after numeric Last-Event-ID, deduplicates, handles split UTF-8/CRLF/heartbeats and bounded retry exhaustion. run_succeeded/run_failed/run_cancelled terminate; waiting_review stays live for human completion. API authenticates before streaming and uses short tenant transactions for bounded batches; release connections between fetches/heartbeats, recheck access during subsequent fetches, and never expose checkpoint output or old raw event payload. Filter by the generated metadata-only projection/redactor. Keep sequence values in JS-safe range on this consumer; impossible-to-represent history fails explicitly rather than rounds.

Execution graph has an equivalent ordered keyboard table with step/status/attempt/time/error text. Controls have labels, status is not color-only, focus survives live updates, and aria-live announces material status changes without announcing every heartbeat. Evidence renders plain text/sanitized content. Browser acceptance must prove actual incremental async mock events, reconnect without missing/duplicate events, successful post-resolution child run, atomic review completion and immutable history. Snapshot replay alone does not close #135.

## Parallel execution and integration order

1. After lead registration, #278 owner implements ADR0024, contract+generated fixtures, migration0011 and compatible occurrence persistence in one prerequisite PR. Independent review covers contract/migration/worker together, with isolated PG and full regression evidence. No implementation begins before registration.
2. Merge the reviewed green #278 prerequisite before dispatching #61 backend and web. They then build in parallel against the same merged contract/mocks/worker. Coordinated worker draining and migration remain a deployment gate, not a hosted operation authorized by this local implementation task.
3. Backend owns main.py and pagination.py; #196 retrieval refactor owns neither and preserves its current router import seam. Existing reader helper imports remain stable or the lead sequences their movement. No two agents edit main.py. Web and backend file sets are disjoint.
4. Backend/web draft PRs push bounded checkpoints and receive independent reviews. Lead integrates only with their complete test evidence, no unresolved material findings and green final CI. Lead alone updates canonical completion/handoff state and merges.

## Verification and acceptance evidence

Use dedicated per-lane/reviewer PG databases, never another agent's database; locked Python3.11 environment and Node24.20.0/pnpm10.33.0. Existing `/private/tmp/fel203-dev` can be used immutably. No install/lock regeneration in implementation lanes. Record baseline fa4cfa2 and final commit SHAs, migration state, counts, coverage floors and actual limitations.

Control: generate/check-generated and full contracts tests, schema fixtures including negative commands, migration fresh install+upgrade from0010, all migration SQL regressions, RLS/immutability/occurrence FK+unique+insert guard tests. Worker: complete extraction+ontology suite with PG and financial/golden compatibility; occurrence concurrency and resolved-parent child run tests. Backend: forged token role and role matrix; hidden tenant objects/cursors/stream404; complete byte/hash/version/corpus/cutoff checks; normalizer block propagation and negative-only canonicalization; no override; same-key replay after head changes; changed-body/actor/resource409; different-key concurrent review/correction one success/one412; group insertion race; overlapping group rollback; unchanged unselected states; merge evidence union/incompatibility; cancel queued/running/waiting_review; terminal event ordering; immutable direct-SQL version history. Web: adapter parity, bounded forward/back/empty/error pages, selection/draft/412 behavior, keyboard/a11y, incremental SSE disconnect/reconnect and correct terminal behavior, browser review/correction/rerun proof.

Commands from implementation checkout with assigned TEST_DATABASE_URL set through local test configuration:

```sh
/private/tmp/fel203-dev/bin/python scripts/db/migrate.py
/private/tmp/fel203-dev/bin/python scripts/db/migrate.py --check
/private/tmp/fel203-dev/bin/pytest apps/api/tests workers/tests/extraction packages/ontology/tests
/private/tmp/fel203-dev/bin/ruff check apps/api workers/src/fel_workers/extraction
/private/tmp/fel203-dev/bin/black --check apps/api workers/src/fel_workers/extraction
/private/tmp/fel203-dev/bin/mypy apps/api workers/src/fel_workers/extraction
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm --filter @fel/contracts generate
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm --filter @fel/contracts check:generated
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm exec vitest run --coverage
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm --filter @fel/web run typecheck
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm --filter @fel/web run test:e2e
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH make ci PY=/private/tmp/fel203-dev/bin
```

Only the control owner runs generate/stages generated artifacts; consumers run check:generated. Execute the repository's migration SQL test runner exactly as current CI does. Do not lower coverage floors or exclude production to pass. No financial golden rewrites. Measure reference p95 create<500ms, 100-item review<1s and reconnect<2s under bounded mock inputs; report observed results, do not infer them from unit passes. Full CI and independent review are required before merge.

## Source anchors for approved behavior

`specs/003-agentic-extraction/spec.md:59`–`:60` (idempotent pinned run), `:70`–`:85` (review/atomicity/history/merge), `:95`–`:96` (conflicts), `:135`–`:140` (normalization and real citation slices), `:148`–`:162` (rerun/review/correction/audit/SSE/pagination); `data-model.md:31`/`:39`/`:47`/`:63`–`:69` (evidence/append-only decisions/versions/transactions); creation cutoff contract `specs/003-agentic-extraction/contracts/extraction-api.yaml:123`–`:128`; accepted ADR0022 `:21`–`:26` and `:50`–`:74`; current worker `normalize/payload.py:191`–`:203`, `validate/duplicates.py:58`–`:80`, `persist.py:330`–`:375`; OpenAPI0.7 `:1055` (opaque ETag), `:2213` (stored run.version); migration0004 `:426`–`:439` (immutable pins), migration0001 `:35`–`:45`/`:87`–`:95` (existing audit and receipt store). These references establish behavior without duplicating the canonical ledger.

### Role-aware web bootstrap

Before rendering controls, fetch the workspace-scoped extraction-permissions
projection. Backend derives its closed allowed_actions list from current
database membership and workspace visibility; web never decodes the configured
bearer for role authority. Empty queues still expose permissions. Responses are
no-store, independent of artifact ETags; every action rechecks authorization.
Backend tests all four actual roles, forged token claims, hidden workspaces and
revocation between permission read and mutation. Web tests reviewer/viewer
controls and permission refresh without discarding a user's draft.
