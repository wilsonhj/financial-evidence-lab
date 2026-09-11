# Extraction review backend implementation breakdown

> PR280 is merged at c105f1b and event-ordering PR283 at 2e3f92b. Implement after #284's candidate-read contract follow-up merges. Use the executing-plans skill for test-first slices. This breakdown does not duplicate or mark the canonical task ledger.

**Goal:** Serve the accepted authenticated extraction run, review, immutable history and live event contracts with atomic database mutations and real evidence revalidation.

**Architecture:** Small extraction routers call transaction-owning services; leaves receive the same tenant connection and never independently commit. Reuse current API auth/RLS, pagination, reader byte checks and the installed pure worker normalizer/validator. No financial reimplementation or general service framework.

**Tech stack:** Existing Python3.11/FastAPI/Pydantic/psycopg/PostgreSQL stack, frozen worker/ontology wheels and generated OpenAPI0.9.0 contract after #284. No new dependencies or provider work.

**Spec:** `docs/superpowers/plans/2026-09-10-extraction-review.md`, accepted ADR0024, `specs/003-agentic-extraction/{spec,data-model}.md`, current root OpenAPI and extraction JSON schemas. Source inspected in `/private/tmp/fel-impl-278` at a7ad7ac plus permissions delta0bb237b. Root owns final published control records and merges.

## Readiness and integration decisions

1. PR280 supplies migration0011, compatible conflict occurrence store, closed review commands/results, immutable validation context, bounded read contracts and workspace extraction-permissions. Its merge is c105f1b; no duplicate schema/migration changes in this lane.
2. EXTRACTION-EVENT-ORDERING under #135 merged as PR283 at 2e3f92b, fixing proven commit-order replay loss in current worker stores. Its plan is `docs/superpowers/plans/2026-09-11-extraction-event-ordering.md`. Preserve its run-first writer locking; it changes no event IDs/schema/hash/version. API/web dispatch now waits for #284 and explicit lead authorization.
3. Existing `apps/api/tests/test_openapi_parity.py:101` forbids serving any path still marked planned. Test each router in an isolated app while building slices. Final router mount and **lead-owned removal of extraction path planned markers** must be one narrow integration commit, under ADR0024 and contract-change authorization. Do not weaken parity, mount incomplete routes or leave generated types stale. Lead owns marker-only edits to root/subordinate contracts and regeneration if needed; implementation does not independently edit shared paths.
4. Permissions is a current contract, not an auth redesign: `GET /v1/workspaces/{workspaceId}/extraction-permissions` returns `{workspace_id,allowed_actions}` with exactly create/cancel/rerun/accept/edit/reject/merge/correct. Derive it from the actual DB-resolved role and visible workspace. Owners/editors get all; reviewers get accept/edit/reject/merge/correct; viewers get an empty array. Use no-store and reauthorize every mutation after this UI hint.
5. Policy selection is deterministic: `SELECT ... FROM extraction_policies WHERE org_id=%s ORDER BY version DESC LIMIT 1`. Rows are immutable, UNIQUE(org_id,version), indexed in descending version order; there is no active flag (`0004_extraction_core.sql:42–72`, M3 data-model:9). “Active policy” means this latest existing version for new creation. Do not create one automatically. A missing policy produces a safe configuration failure and no run/job/event/audit/receipt side effects.
6. `ExtractionRunCreate` has **no policy_id**, but has optional nullable **corpus_version_id** (`openapi.yaml:2863–2938`). Honor an explicit valid active/superseded corpus using existing `require_corpus`; omitted/null chooses the unique current active corpus (`0002_corpus_core.sql:152–163`). `require_corpus(None)` only skips validation; it does not select a pin. Missing current corpus fails before enqueue. Return only the selected pins exposed by the closed `ExtractionRun` representation. That response also has no `policy_id`: persist and verify the immutable policy binding through database/worker tests, without adding an uncontracted response field. Web need not request policy IDs or a new policy-list endpoint.

## Exact implementation ownership

ADR-0024 Amendment 1 / #284 updates the planned contract to 0.9.0. Proposal
payload reads can use ExtractionCandidateFields (`extraction-candidate-fields/v1`)
when the strict financial schema fails or any JSON numeric leaf is not a safe
integer (absolute value above 9,007,199,254,740,991 or fractional; exclude booleans
and numeric strings). This recursive display predicate changes no financial rule.
Read the bounded stored JSON text before ordinary numeric decoding to classify it
losslessly; Python's standard JSON decimal/int hooks suffice. Remove only legitimate
worker evidence extensions before classification; unknown fields still fail schema.
For the text branch, SQL extracts only present allowlisted public fields as
`(payload -> key)::text`, yielding strings with the persisted JSON value/type.
Missing remains absent and JSON null becomes `null` text. Do not reconstruct those
strings from decoded floats, alter stored payloads/hashes or invent fields.
Preflight payload bytes at 1 MiB before fetching and bound each displayed field
to 65,536 characters; overflow is explicit 413, never truncation. Proposal reads
allow zero evidence, while approved/review/correction schemas stay strict.
Project actual blockers to safe failure diagnostics even when stored `ok` is true;
never echo raw summaries, submitted values or unknown control-field names. A text
wrapper by itself is neither an approval nor a newly invented financial blocker.
Add fixtures/tests for malformed values, unsafe/fractional numbers, nested fields,
null/missing, omitted controls, empty evidence, stale `ok` and strict inputs.
Resolve selected claim IDs through their retrieval run/workspace, citations/items
and source spans, with complete scoped byte verification. The default extraction
mock cites fixed span IDs: lifecycle tests must seed those real fixture pins or
use existing scripted-mock injection, without weakening citation checks.

New `apps/api/app/extraction/` files:

| File | Responsibility |
| --- | --- |
| `__init__.py` | Export composed extraction router. |
| `models.py` | Closed transport models matching generated schemas, strict decimal strings and exact command variants. No services/SQL imports. |
| `serializers.py` | Deterministic public projections and quoted representation/head/group ETags; strip internal evidence/control fields. |
| `routes_runs.py` | Permissions, run list/create/detail/DELETE cancel/rerun, proposal list/detail transport. |
| `routes_review.py` | Review and correction transport, method/header/body limits and role requirements. |
| `routes_history.py` | Steps, conflicts, approved detail/versions/immutable version detail/event-history reads. |
| `routes_events.py` | Authenticate/validate stream request, response headers, cancellation/disconnect boundary. |
| `runs.py` | Create/cancel/rerun transaction and exact queue payload construction. |
| `review.py` | Atomic accept/edit/reject/merge/bulk transaction. |
| `corrections.py` | Immutable approved-version append and head change transaction. |
| `conflicts.py` | Complete bounded membership discovery, digest, resolution and recorded-winner checks. |
| `evidence.py` | Complete source/pin/cutoff SQL plus actual canonical slice loading and hash verification. |
| `validation.py` | Composition of existing pure financial normalizer, validator and citation checks. |
| `receipts.py` | Canonical request hash, same-key transaction serialization and exact stored-response envelope. |
| `reads.py` | Bounded ordered SQL/read projections and extraction pagination scopes. |
| `events.py` | Metadata-only event SQL/projection, bounded replay batches and SSE framing/polling. |

Existing production files: `apps/api/app/main.py` router mount only; `apps/api/app/pagination.py` closed additive extraction endpoint/filter/key support. New tests only `apps/api/tests/extraction/**`, including local test fixtures below. Keep new modules near100–350 lines, at/below approximately500. If an actual module exceeds that, request a named small SQL leaf; do not pre-create a generic repository/service framework. Backend owns main/pagination exclusively; retrieval #196 and web own neither.

Dependency graph: main → routers → runs/review/corrections/reads/events → leaves → existing app dependencies/db/errors/reader and pure worker/ontology. Models import no services. Worker imports no API. Use one explicit connection for each mutation; no leaf calls tenant_connection or commits its caller's transaction.

## Verified reusable seams and their limits

- `app.dependencies.get_tenant_context` and existing membership resolution verify bearer identity and resolve role from DB. Token role claims are not authority. `app.db.tenant_connection` applies fel_app and tenant claims; `snapshot_read=True` provides consistent read transactions. Never substitute worker-role access.
- `app.errors.api_error` and `app.observability.record_audit_event` provide the existing error envelope and same-transaction audit. Return safe IDs/codes, not raw exceptions/evidence/provider content.
- `app.reader` canonical text/section/span helpers provide storage containment, per-object byte ceilings, offsets and content hash checks. `evidence.py` must separately prove complete requested IDs, document version, successful parse, corpus membership, entity and publication cutoff. A known span ID or stored citation_status does not prove current bytes.
- Worker `normalize.pipeline.normalize_payload`, `validate.pipeline.validate_proposals`, `citation_status_for`, `validate.schema.validate_payload_item`, `hashing.canonical_json/hash_json`, and installed ontology are reusable. `scripts/runtime/install.sh` already installs the worker wheel in the API environment; no new package is needed.
- Normalization returns a payload and blockers. Carry `_normalizer_blockers` into validation exactly as the current normalize stage does. Strictly reject unknown kinds before batch validation; validate_proposals can otherwise skip them. Require one output draft per input and retain source-row identity separately from recomputed draft IDs. Never overwrite proposal IDs/hashes with revalidation draft identity.
- Preserve current batch accounting/duplicate/conflict checks using the complete bounded relevant peer set. Map diagnostics back to stored proposal IDs without assuming recomputed IDs are unique across duplicate inputs. Revalidate recorded winner payload/evidence when evaluating a later edited alternative. Oversized/incomplete peer or membership sets fail explicitly, never validate a truncated page.
- Worker citation helpers verify hashes against evidence inputs; construct those inputs only after reading and checking real canonical slices. Ignore client-supplied internal citation status/hash assertions. This is deterministic evidence integrity, not an invented semantic entailment model.
- Public financial payload schemas omit worker-only extension/control fields. Serialize public payload keys explicitly; retain immutable original proposal bytes and stored provenance. NULL confidence is “Uncalibrated”; do not invent scoring or pass status.
- Existing `queue.enqueue` is not a drop-in API call: it reads tuple rows, and its dedup UPDATE conflicts with fel_app's narrower jobs grants. Use a small explicit INSERT on the existing tenant transaction, with every required existing job field. Test the resulting envelope through `handle_extraction_run` and its persisted-pin binding. No worker/queue behavior changes belong here.
- Current `PostgresEventStore.append` returns a memory-local event ID; API must use the actual database INSERT RETURNING id/read row. Keep the existing metadata redactor and public event schema. Existing retrieval read SQL demonstrates size-before-payload and cap+1 patterns; avoid coupling extraction to retrieval private helpers.

## Shared transaction and validation rules

Use authorization → deterministic same-key receipt lock/read → discovery → sorted runs → sorted groups → sorted proposals → sorted approved heads → re-read state/membership/version → validate → writes/receipt → one commit. The receipt advisory lock is the accepted request-serialization lock and always precedes resource locks; never acquire it after a run lock. This is distinct from the rejected extra event advisory lock. If discovery expands an earlier lock class, roll back/restart bounded discovery instead of locking it late. Bound genuine serialization/deadlock retries; do not retry a failed business precondition as a new request.

Receipt envelope in existing response_body is `{receipt_version:"extraction-receipt/v1",request_hash,response_headers,body}`; status remains response_status. Canonical hash includes actor/resource/action/body/preconditions. Sort set-like IDs, preserve meaningful arrays. Same key/different request409; same key/same request returns exact original status/body/ETag/Location even after later resource changes. Authorization still runs on replay. Respect existing review UNIQUE(org_id,idempotency_key,action), including cross-workspace collisions; no receipt-table migration.

Run ETag hashes the complete exact deterministic response representation, including usage/status/cancellation. Read from one snapshot, compare under run lock; no clock-derived fields or reliance on run.version increments. Immutable version/head and complete group membership ETags use their corresponding contracted projections. Any expected-version map must exactly equal the selected/membership ID set; missing and extra entries are rejected.

Use frozen source cutoff/corpus/policy for existing artifacts, current deterministic executable validation rules for every new approval/correction, and immutable validation_context for successful new versions. Missing historical rules needed for safe revalidation blocks mutation while history remains readable. normalize/v2 may canonicalize only high < low < 0 under the accepted Decimal/common-scale rule; positive/mixed inversions and independent numeric/unit/citation/accounting blockers cannot be overridden. No new financial repair, FX, aggregation or calibration.

## Test-first vertical slices

Each slice: add the named failing tests; run them and record the actual failure; implement the minimum owned files; rerun focused tests; commit the bounded checkpoint and update the draft PR. Do not mark canonical tasks complete. Until final integration, tests create an isolated FastAPI app including the real extraction router and established exception/auth dependencies; they do not weaken root parity.

### 1. Authorized bounded reads and permissions

Files: models/serializers/reads/routes_runs/routes_history plus `tests/extraction/conftest.py`, `test_reads.py`, `test_permissions.py`, `test_pagination.py`. Local fixtures use a dedicated lane database/current migrations, unique tenant data and actual RLS; do not reuse retrieval-only freshness detection or edit its fixtures.

RED examples: viewer permissions is empty; forged owner claim for DB viewer remains empty; foreign workspace404; equal-timestamp pages traverse forward/back without loss; empty continuation remains scoped; wrong run/corpus/filter cursor422; oversized conflict membership413 names the offending resource. GREEN: closed transport models, tenant-qualified SQL, default50/max200 and cap+1 lookahead, complete details and deterministic ETags. Steps omit checkpoint output; approved history includes immutable parent/context and keeps legacy NULL context readable.

### 2. Exact receipts and command boundaries

Files: receipts/models plus `test_receipts.py`, `test_command_validation.py`. RED: same-key two connections yield one stored result; replay after later head change returns original body/headers; changed actor/body/resource/precondition409; role revoked before replay is denied; failed transaction leaves no success receipt. Reject oversized1MiB body, duplicate/extra version IDs, unknown properties, malformed UUID/decimal, unsupported action shape and selection>100 before mutation. GREEN: one deterministic request lock and existing receipt table, no new response reconstruction. Test exact receipt envelope remains internal.

### 3. Create with real source bytes and existing queue envelope

Files: runs/evidence/routes_runs plus `test_run_creation.py`, `test_evidence.py`. RED: policy version2 wins over1; explicit superseded corpus honored; null selects unique active; missing policy/corpus creates nothing; mixed valid/invalid selected IDs reject whole request; byte/hash/offset/parse/corpus/entity/cutoff failures reject before enqueue; request limits cannot widen selected policy. GREEN: effective cutoff=min(workspace,request), resolve all source_span_ids/claim_ids, pin immutable policy/ontology/workflow/mock provider/model, sort text-free manifest and producer occurrence policy `run/v1`, hash with existing algorithm; atomically insert run+job+run_queued+audit+receipt.

Keep inline verified evidence bytes only in the existing bounded durable job envelope, never run/event/audit/errors. Use the existing mock provider/model configuration explicitly; no caller-chosen provider, no fallback to live. Bind a deterministic tenant job identity to the new run (using the run UUID as job UUID is a small producer-owned convention with no schema change) and test lookup/payload consistency. Existing legacy runs require verified tenant-bound matching job payload; no guessed job ID. Run the created job through the actual durable handler on a worker connection with the mock provider and assert waiting_review proposals/citations/pins; no paid calls.

### 4. Coherent cancellation and child rerun

Files: runs/routes_runs plus `test_run_controls.py`. RED: stale complete-representation ETag412 after usage/status change even if integer version unchanged; queued/running cancellation timestamps update run and its verified job atomically; waiting_review cancellation appends run_cancelled before terminal update and preserves proposal states; new-key terminal409 and same-key exact replay. GREEN: DELETE follows current contract; cooperative worker cancellation remains existing behavior. Resolve legacy jobs by tenant/kind and immutable run payload with bounded ambiguity check; absent/ambiguous binding fails closed rather than updates a guessed job.

Rerun RED: unchanged parent/proposals, new ID/parent link, same source/corpus, min(parent,current workspace cutoff), ineligible retained source fails with no child/job, explicit new run occurrence succeeds after parent adjudication. GREEN: reuse creation leaves with explicit retained pins/current executable policy choices from the accepted design; never silently drop evidence or reopen old groups. Verify missing executable historical context fails safely instead of silently repinning old source meaning.

### 5. Real deterministic validation composition

Files: evidence/validation plus `test_revalidation.py`. RED cases use actual canonical fixture bytes and existing worker outputs: positive/mixed range reversal blocked, allowed all-negative range canonicalization retained, sign/scale blocker propagated, invalid decimal strings rejected, accounting peer outside selected subset still blocks, omitted/altered citation bytes block, unknown kind cannot disappear, duplicate generated draft identity does not misattribute stored rows. GREEN: compose existing functions, preserve raw source and original hashes, generate complete source_runs validation_context. No copies of financial algorithms or new provider judgments.

### 6. Atomic accept/reject and optimistic bulk

Files: review/routes_review/events plus `test_review_atomicity.py`, `test_review_concurrency.py`. RED: accept creates immutable record/version and exact result; reject creates none; one invalid item rolls back all states/reviews/approved rows/events/audit/receipt; two different keys against same version produce one commit/one412; same-key concurrent calls return one exact result. GREEN: sorted lock/re-read, immutable review record, selected state changes and approval writes in one transaction. Complete affected waiting_review runs only when all proposals terminal and no related group open; event before terminal update. Never automatically dispose unselected proposals.

### 7. Explicit conflict adjudication, edit and merge

Files: conflicts/review/validation plus `test_conflicts.py`, `test_edit_merge.py`. RED: missing overlapping group or stale complete membership412/blocked result; concurrent real worker member insertion versus API resolution serializes at run→group and leaves no hidden new member; winner selection outside selected IDs rejected; independent invalid numeric/citation blocker cannot be waived. Assert unselected states/versions unchanged and resolved history cannot reopen/rewrite.

Later unchanged contradictory acceptance must fail against stored winner; explicit edit removing contradiction can pass only after full revalidation. Empty winners allowed only if this transaction leaves every member rejected/superseded. Edit requires one complete replacement per selected ID and stores patch in immutable review, preserving original payload/hash. Merge checks exact comparable kind/entity/metric/period/dimensions/definition/unit/currency, copies explicit payload_source_id, unions/deduplicates/verifies evidence, creates one new logical record and supersedes selected inputs. No arithmetic or implicit existing survivor. Incomplete/incompatible merge409; all failures roll back the batch.

### 8. Immutable corrections and history

Files: corrections/routes_review/routes_history plus `test_corrections.py`, `test_history.py`. RED: two corrections on same head produce one success/one412; replay original correction after a later correction returns original immutable version/ETag; old version/evidence unchanged; history/detail links and parent chain reconstruct state; historical NULL validation context remains visible but mutation cannot invent missing provenance. GREEN: lock affected runs before approved head, verify If-Match, validate full replacement against frozen sources/current rules, append n+1 and audit/receipt, move only head pointer/version. No correction action enum or new migration.

### 9. Bounded live SSE and stored events

Files: events/routes_events/reads plus `test_events.py`, `test_sse.py`. Requires merged event-ordering prerequisite. RED: authenticated stream emits an event inserted after connection opens; reconnect after real table ID yields later events exactly once; wrong-run/foreign-tenant hidden404; invalid/unsafe integer resume rejected; waiting_review remains live; terminal event closes after delivery; disconnect releases resources; role revocation stops access during subsequent batches. Seed a legacy payload containing forbidden raw keys and assert output never reveals them.

GREEN: short tenant transactions per batch, release pooled connection between polls/15–30s heartbeats, no-store streaming, cap200 rows/64KiB frame, metadata-only projection, strictly increasing actual numeric IDs within run and safe JS range. Probe payload byte size before fetching oversized JSON; fail explicitly with safe resource IDs. Never return checkpoint output, silently skip a malformed committed event or hold a database transaction for the stream lifetime. Keep event history pagination separate from live polling and test forward/back/empty pages.

### 10. Mount, parity and end-to-end mock acceptance

Files: `__init__.py`, main router mount, final additive pagination entries, `test_routes.py`, `test_mock_lifecycle.py`. Lead supplies same-commit marker-only shared contract changes. RED contract-route parity before mount; GREEN all accepted extraction operations served and no planned marker points at a served path. Keep existing reader/retrieval tests unchanged.

Run actual create→durable mock job→waiting_review→conflict adjudication→review completion→immutable correction/history→child rerun flow, with forged-token/foreign-org negatives and rollback evidence. Feed live SSE during the flow, not only stored snapshots. Independent web uses generated contracts on disjoint files; coordinate stable error/resource details and selected pins without changing schemas independently.

## Verification and handoff

Before implementation record merged baseline SHA, fresh migrated lane database and full API/worker baseline. Configure only the assigned database; never modify another agent's DB or immutable `/private/tmp/fel203-dev`. No installs/lock regeneration. Focused commands from the implementation checkout:

```sh
export FEL_REQUIRE_DB=1
: "${TEST_DATABASE_URL:?Set the dedicated local test database URL before running tests}"
/private/tmp/fel203-dev/bin/pytest apps/api/tests/extraction -q
/private/tmp/fel203-dev/bin/pytest apps/api/tests/test_openapi_parity.py -q
/private/tmp/fel203-dev/bin/pytest apps/api/tests workers/tests/extraction -q
/private/tmp/fel203-dev/bin/ruff check apps/api/app/extraction apps/api/tests/extraction apps/api/app/main.py apps/api/app/pagination.py
/private/tmp/fel203-dev/bin/black --check apps/api/app/extraction apps/api/tests/extraction apps/api/app/main.py apps/api/app/pagination.py
/private/tmp/fel203-dev/bin/mypy apps/api/app
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm --filter @fel/contracts check:generated
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH pnpm exec vitest run packages/contracts
PATH=/Users/hirokazu/.nvm/versions/node/v24.20.0/bin:$PATH make ci PY=/private/tmp/fel203-dev/bin
```

Run required full coverage/CI without lowering floors or excluding production; report meaningful RED/GREEN failures, final counts, exact heads, migration state and limits. Measure accepted mock-reference p95 create<500ms,100-item review<1s,reconnect<2s; record observed values and workload, not inference from unit passes. Final independent review must inspect RLS, real-byte revalidation, complete peer sets, exact replay, lock order/concurrency, immutable history and live streaming. Root alone approves/merges and updates canonical completion.

Remaining implementation risks are concrete, not contract extensions: complete bounded financial comparison peers, legacy job binding for cancel, and historical context sufficient for correction. Fail closed where historical data cannot establish these facts, keeping old history readable. No new policies/config API, provider adapter, confidence algorithm, migration or financial contract is authorized by this backend breakdown.
