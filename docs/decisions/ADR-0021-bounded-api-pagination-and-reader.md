# ADR-0021: Bounded API pagination and evidence reads

Status: Accepted for implementation under the owner's backlog execution request

Date: 2026-09-10

Issue: #191; follows ADR-0016 and contracts 0.6.0

## Context and authorization

PR #232 delivered admission, pooling and durable metering; PR #261 preserves
provider provenance. The remaining document/workspace/run lists, reader
assembly and event/trace reads are unbounded. The owner requested complete
backlog implementation and reviewed integration. This decision accepts the
bounded design below and coordinates the API, contracts and actual consumers.
It supersedes ADR-0005's transport-only oversized-reader posture specifically
with the explicit scope and size errors below; citation/version/integrity and
cutoff rules remain binding. It does not certify provider spending or live gates.

### 3.1 Compatibility: additive 0.7.0 only with explicit pagination

Do **not** change a formerly complete bare array into a silently truncated default array, or call a changed required envelope an additive release. `VERSIONING.md` treats changing field meaning/required shapes as breaking. ADR-0005 also explicitly describes complete sibling evidence and originally permits no overflow workaround except transport compression/streaming. ADR-0021 must supersede that size-posture paragraph, not quietly reinterpret it.

Accepted 0.7.0 release:

1. Add optional `limit`, `cursor`, and `order=asc|desc` to the three existing list operations. `limit` explicitly opts into pagination, defaults to 50 **inside page mode**, maximum 200; `cursor` implies page mode and carries the original limit. If neither is supplied, preserve complete legacy successful bodies only up to the bounded legacy ceiling 50. Probe 51 rows and return declared 409 `PAGINATION_REQUIRED` on overflow, with restart parameters in `error.details`; never return a partial success to an old caller. This is an explicit new error response plus opt-in behavior, not an undocumented default truncation.
2. Keep workspace/document 200 bodies as their existing arrays. Return `X-FEL-Next-Cursor` and `X-FEL-Previous-Cursor` only when present, plus `X-FEL-Page-Limit`; optionally a relative same-origin `Link` representation of the same continuation. Query snapshots keep `runs` and their existing metadata, using the same headers for the run page. No required envelope replacement.
3. Reader page mode is explicit (`sibling_limit`, `sibling_cursor`, `sibling_order`), bounded separately at default 10, maximum 20 sibling blocks. Add optional top-level `sibling_page` metadata to `reader-response/v1` (`x-fel-version` 1.1.0), required by the page-mode producer/consumer branch but absent on legacy successful bodies. The original schema remains valid for old fixtures. Metadata includes returned count, next/previous cursor, and `complete` (whole sibling set present, not merely 'last page').
4. Add `include_siblings=false` as an explicit target-only reader option. It returns complete target evidence, `siblings=[]`, and `sibling_page.scope='excluded'`. An issuer's long history cannot prevent opening an otherwise in-bound oldest or newest target filing. The web must disclose that related evidence has not been loaded and expose sibling navigation/comparison.
5. Legacy full-reader requests probe/count after the **selected parsed-version evidence gate**; on excessive sibling count return 409 `PAGINATION_REQUIRED`, not a partial v1 response. Oversized *individual* document evidence returns declared 413 `READER_TOO_LARGE` with a safe reason and known target metadata link. This does not make oversized canonical artifacts falsely verifiable; original filing links remain available. Limits are an explicit resource boundary, not a completeness claim.
Ship the API and actual consumers together. Contract 0.7.0 is next after the
current 0.6.0; schema shapes remain compatible through optional additions and
explicit page-mode behavior. No normal in-bound legacy success is partial.

An optional document_version_id selects an explicitly pinned parsed version of the otherwise-visible target; it must belong to that document and agree with any published corpus pin. Missing, foreign-document or visibility-excluded versions retain uniform 404 behavior. When omitted, existing selection rules apply. The selected version is bound into every sibling cursor and retained across target-only and related-page requests.

### Cursor and SQL mechanics

Use a small typed continuation codec in `app/pagination.py`: canonical JSON
encoded with URL-safe base64, maximum token length 2,048 bytes. Reject duplicate
JSON keys, unknown fields/versions, malformed UUIDs/timestamps/keys, booleans as
integer limits, limits outside 1–200 and wrong route/resource/filter scope with
422 `INVALID_CURSOR`. Fields include version, endpoint, canonical organization
and resource IDs, normalized cutoff/corpus filters, order, limit, seek direction,
first-page high-water key and anchor. Reader scope also includes target selected
version and effective cutoff. Keep route-specific anchor types explicit.

Cursors are untrusted continuation data, not authorization or a promised signed
artifact. Do not add HMAC, expiry or a new signing credential for this contract.
A caller can construct a valid alternative continuation within its authorized
scope. Every page independently authenticates and reapplies organization, RLS,
resource visibility, cutoff and corpus-pin eligibility before SQL LIMIT. The
codec checks scope consistency to reject accidental cross-context reuse, not
to replace those database boundaries. Never log raw cursors or credentials.

Use keyset queries with LIMIT limit+1 and parameterized seek/high-water values,
never OFFSET or fetch-all then slice. Total keys: workspaces(created_at,id),
documents(published_at,accession COLLATE "C",id), query runs(started_at,id),
siblings(the document key), persisted events(seq). Corpus/parsed eligibility
precedes the limit. Previous-page queries reverse seek then restore presentation
order; oldest/newest and next/previous controls keep all history reachable.
High-water selection uses the same predicates as the first page.

**Honest concurrency contract:** keyset order is deterministic for unchanged rows; it is not a cross-request MVCC snapshot. The high water excludes newly appended top-end rows from an existing traversal, but backfilled/in-flight commits and mutable workspace/run status may become visible between requests. Refresh starts a new traversal; do not claim 'all database rows as of first HTTP request'. A published immutable corpus pin gives repeatable document/version selection; each reader response still uses `snapshot_read=True`. For unpinned reader browsing, fix the target version in the cursor, retain cutoff and one selected version per sibling block, and label cross-page coverage as browsing rather than an immutable whole-entity comparison. If immutable **cross-page** history comparison is required, require/select a published corpus pin for that operation; never manufacture snapshot guarantees from `created_at <= now()` or keep a PostgreSQL transaction open across HTTP requests.

### 3.3 Reader assembly bounds without orphaned evidence

Accepted fixed resource limits: 2,000 sections, 10,000 target spans, 10,000 facts per document, 16 MiB canonical object, 32 MiB total response budget, 32 MiB total hash-verification slice bytes per document; 10 default / 20 max sibling blocks. These are **resource limits**, not acceptance claims about the live corpus. Before enabling, offline fixture/performance evidence must demonstrate ordinary large 10-Ks fit; report overflow honestly if they do not. Use fixed positive limits; do not add an unbounded or zero-means-unlimited escape hatch.

- Add `LIMIT cap+1` to `_SECTIONS_SQL`, `_ALL_SPANS_SQL`, `_FACTS_SQL`, `_REFERENCED_SPANS_SQL`. Validate counts before materializing section strings/hashing. No partial target block is returned: a fact must still have a same-block source span and every span must remain inside a selected-version section with the correct hash.
- Use one bounded SQL candidate query selecting parsed-visible siblings; eliminate Python scanning of unparsed siblings and N+1 `_select_version` calls. Latest-parsed uses the exact ADR-0005 created/parser/normalizer/UUID total order; pinned selection retains the duplicate-pin corruption check (LIMIT 2 per document, never arbitrary LIMIT 1).
- Fetch target first so page membership never displaces it. Opening a target-only reader is independent of sibling-history size. For sibling page overflow due to a single huge block, identify the resource boundary and offer that sibling's metadata/original filing link; do not silently skip the sibling and advance past it as if read.
- Check canonical object size before decoding (`open` + bounded read of cap+1 bytes; `stat` alone is not a read bound). Retain resolved-root path containment, strict UTF-8 decoding and integrity error distinctions. Do not issue object-provider calls in this package.
- Bound total section content length **before slicing**: nested/overlapping sections can repeat the same canonical text, so a 16 MiB file is not a 16 MiB response guarantee. Also bound the summed span lengths to prevent 10,000 enormous overlapping hashes from becoming unbounded verification CPU.
- Return 413 with `error/v1`, `code='READER_TOO_LARGE'`, safe `details.resource`, `details.limit_kind`, `details.limit`; do not disclose filing text or assume this means not-found. Hash/version failures remain 500 `INTEGRITY_ERROR`. Missing/cutoff-hidden/unparsed target 404 behavior stays byte-equivalent as ADR-0005 requires.
- `_close_fact_links` currently strips links not local to the response. In page mode, do not interpret absent links or absent related facts as evidence of no amendment/duplicate. The UI must carry page coverage, show 'related history incomplete', and permit loading comparison pages. Keep `duplicate_of`/`restates` response-local unless a separately declared resolvable reference shape is added; do not introduce dangling IDs under the frozen shape.
- `EvidenceReader` currently labels `original` as effectively current and computes global duplicate/amendment state from all loaded documents/facts. Gate any authoritative whole-history status on complete loaded coverage or a corpus-pinned server-derived relation. On partial pages, show an explicit incomplete comparison state. A bounded indexed metadata query for predecessor/latest applicable amendment is preferable to draining all sibling evidence merely to paint the banner; if added, declare an optional relation summary with its pin/cutoff in ADR-0021 and test it independently.

### 3.4 Trace and events: bound work without destroying replay

`get_retrieval_run` is a complete trace, not an ordinary row-list endpoint. Normal retrieval already has configured candidate/context/variant budgets, but persisted event/claim/citation tables and JSON payloads are not structurally bounded by those settings. Do not assume the producer's current happy path is a safe read bound.

- `_sse_stream` should read batches of at most 200 ordered rows, close the tenant connection before yielding a batch, update the last emitted `seq`, and continue through the captured high-water sequence. Never add a single `LIMIT 200` then call the replay complete. More than 2,000 events must still reach the terminal event. Reconnect/disconnect uses existing `Last-Event-ID` strictly after the last delivered sequence; no synthesized terminal event and no event-schema change.
- Emit existing heartbeat comments while waiting, every 15–30 seconds; respect cancellation and the existing HTTP duration policy. Batch boundaries are not reconnects. The client already deduplicates and resets retry count on progress; preserve this.
- Complete JSON trace reads must preflight bounded collection/byte limits and preserve byte-stable bodies for in-bound traces. Suggested caps: 2,000 distinct candidates / 32,000 lane contributions, 10,000 events, 1,000 claims, 16,000 citations, 16 MiB serialized trace, 256 KiB single event payload. Read cap+1/probe bounded IDs before fetching large payloads; enforce the total byte budget incrementally while reading bounded batches, not after materializing 10,000 individually large payloads. If oversized, return explicit 413 `TRACE_TOO_LARGE`, not a clipped trace accepted by `validateTrace`.
- Keep the complete-trace read semantics in this residual. Add bounded event-history inspection via `GET /v1/retrieval-runs/{runId}/event-history?limit=50&cursor=&order=` returning new `RetrievalEventPage {run_id, items, next_cursor, previous_cursor}`. This permits oldest/newest navigation independently of whole-trace size; SSE still reaches all representable events. An indivisible event beyond the frame ceiling yields an explicit size/integrity failure rather than dropping its sequence. Probe the first batch before SSE headers; an error then can still be 413. If a later batch encounters corrupt/oversized evidence after 200 headers, abort the transport and have the consumer surface interrupted replay, never synthesize a persisted run failure or treat EOF as successful completion. The REST event-history read returns the typed size error for the offending window.
- If a fixture demonstrates legitimate candidate/claim history beyond the complete-trace ceiling, report the resource boundary and seek a scoped follow-up decision before inventing another trace contract. Do not fake full `RetrievalTrace` with partial candidate/claim arrays. The mandatory current delivery is bounded full-trace-or-explicit-error, plus complete resumable event access.

### 3.5 Actual web boundary changes

Use explicit page return types at the hand-written data-source boundary, not `Promise<DocumentMeta[]>` silently representing one page:

```ts
type Page<T> = {
  items: T[];
  nextCursor: string | null;
  previousCursor: string | null;
  limit: number;
};
type PageOptions = { limit?: number; cursor?: string; order?: 'asc' | 'desc' };
// Entity is explicit: don't invent a global cursor by flattening independent entity pages.
listDocuments(entityId: string, options?: PageOptions): Promise<Page<DocumentMeta>>;
getQuery(queryId: string, options?: PageOptions): Promise<QuerySnapshot & { runPage: Page<RunSummary> }>;
getReader(documentId: string, options?: ReaderPageOptions): Promise<ReaderResponse | null>;
```

- Home: paginate the selected configured entity with oldest/newest/previous/next controls. Switching entity, cutoff or pin resets cursors. Preserve access to every configured entity with a selector. Do not auto-drain every API page in the server component and recreate an unbounded response.
- Add optional `corpus_version_id` to the document listing itself, applying selection before pagination; remove `listDocuments`' per-document `getReader` pin-validation loop. Keep `DocumentMeta` identity unchanged; version-to-document lookup uses the separate bounded reference endpoint below.
- Replace Observatory's whole-corpus `buildDocumentIdByVersionId(source)` scan with `resolveDocumentVersions(versionIds)` over the actual trace candidate IDs, max 200 per request. New authenticated `GET /v1/document-versions/resolve?document_version_id=...&as_of=&corpus_version_id=` returns new `DocumentVersionReference[] {document_version_id, document_id}` for visible parsed versions only; unknown/hidden IDs do not resolve. Apply the trace's corpus/effective cutoff, not unrelated current runtime defaults. Deduplicate before request; use bounded batches for traces larger than 200 IDs, never all corpus filings.
- Run page: keep question/plan, add run-history pager and explicit oldest/newest controls; compare selection must work for runs beyond the first 50. Direct run IDs remain independently readable.
- Reader: load the target-only snapshot first, preserve span deep links, then load bounded related pages explicitly. `reader-loader.ts` must retain selected target version and coverage. `EvidenceReader`/`FactPanel` must not treat partial facts as a complete duplicate index or label an unvisited amendment chain 'Current'. Navigate the original/newest filing even when many quarantined/older siblings exist.
- Treat malformed continuation metadata, repeated/non-progressing cursors, wrong-version reader pages and mismatched cutoff/pin as contract failures. Never follow an arbitrary absolute continuation URL while attaching bearer authorization; build the known route with the opaque cursor or enforce same-origin/path strictly.
- Mirror this in fixture sources and mocks. No generated-client-only 'consumer update' claim: the production sources call fetch manually and must be changed/tested.


## Ownership, indexes and acceptance

The execution ledger owns exact paths. Reserve additive migration
`0010_api_read_indexes.sql` and its harness only for indexes demonstrated
necessary by representative EXPLAIN plans; never edit historical migrations.
Candidates are composite tenant/time/UUID indexes for workspace/run lists,
entity/publication/accession/UUID for documents, selected parsed-version lookup,
and version/ID or offset indexes for facts/spans. Reuse existing event/section
indexes. No new cache, generic repository layer or service is needed.

Prove both-direction traversal over more than 200 tied-timestamp records without
omission or duplication on fixed fixtures; tenant/cutoff/pin exclusion before
limits; strict malformed cursors; visible oldest/newest access. Prove target
integrity, exact-limit/over-limit behavior, overlapping-section byte and hashing
bounds, many ineligible siblings, safe version resolution and no false complete
history claims in UI. Replay more than 2,000 persisted events across bounded
batches and reconnect boundaries with all sequences and terminal evidence
preserved. Overflow must return typed errors rather than truncated success.

Run real migrated PostgreSQL tests, contract/client generation parity, actual
HTTP/fixture consumer tests, reader cross-stack and browser tests, and current
security/type/format CI. Existing request status/duration telemetry remains;
`app/observability.py` is serialized under #203 and excluded from this dispatch.
Canonical task completion remains integration-lead owned.

Issue #195 retains production provider selection, usage result contracts and
accurate pricing/budget enforcement. Pagination does not prove that live
provider costs are enforced. Issue #191 stays open until that residual is
verified or explicitly transferred with accepted linked ownership.
