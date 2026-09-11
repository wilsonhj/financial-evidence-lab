# Retrieval API Complexity Split Implementation Plan

> Execute inline using the executing-plans skill under accepted ADR-0017 after the PR #272 merge. A designated implementation agent owns the five source files; a different reviewer approves the result. Existing tests remain unchanged.

**Goal:** Finish #196's API portion by splitting the retrieval module into focused files around 500 lines while preserving every observable behavior and existing patch seam.

**Architecture:** Keep `app.retrieval` as the public router and runtime patch boundary. Move persistence, query storage, pipeline execution, and bounded trace reads into four explicit helper modules. Keep sensitive control functions in the facade; supply explicit dependencies at invocation time for the two larger moved functions that consume patched facade names.

**Tech stack:** Existing Python 3.11, FastAPI/Pydantic, psycopg/PostgreSQL, locked provider/retrieval packages. No new dependency.

**Sources:** Exact reviewed source `e590bc94134720407726e59cac2519416e1f2adf`, particularly `apps/api/app/retrieval.py` (about 1,630 lines), existing `apps/api/tests/test_retrieval*.py`, ADR-0017's narrow #196 split, ADR-0021's bounded reads, ADR-0006 retrieval invariants, and the canonical plan. This document does not restate or change canonical task completion.

## Dispatch and scope

Do not start implementation until main contains the merge of PR #272. Record that actual main SHA as the mechanical-comparison baseline; inspect any source delta from e590bc9 before applying this inventory. GitHub closed #196 at 00:18 UTC on September 11. Preserve that administrative state; the earlier extraction split did not satisfy the API portion, which remains authorized by the owner and the committed execution plan.

Exact allowed paths:

- `apps/api/app/retrieval.py`
- `apps/api/app/retrieval_queries.py` (new)
- `apps/api/app/retrieval_run_store.py` (new)
- `apps/api/app/retrieval_pipeline.py` (new)
- `apps/api/app/retrieval_reads.py` (new)

No `apps/api/**` wildcard. Exclude `app/main.py`, `reader.py`, `corpus.py`, `pagination.py`, extraction modules, tests/goldens, contracts, migrations, configuration, dependencies, handoff files and canonical specs from implementation ownership. The lead registers this exact scope in workstreams.yaml. This permits #61's extraction API/main integration to proceed without overlapping source ownership.

The remaining API target is retrieval's responsibilities, not a repository-wide 500-line enforcement exercise. Do not split the already reviewed reader merely because it is long. Around 500 means a readability target: an approximately 530-line facade/read module is preferable to another artificial abstraction or changed patch semantics. Do not compress formatting/docstrings to meet a numeric ceiling.

## Exact module inventory

Line estimates include ordinary imports/spacing and may vary with required annotations. Total code can increase modestly for explicit wrappers/dependencies; no feature expansion is justified.

| File | Responsibilities and exact original definitions | Estimate |
|---|---|---:|
| `retrieval.py` | Existing `router`, all seven route decorators and public endpoint names/signatures; retained control functions below; explicit reexports and call-time dependency construction | 480–550 |
| `retrieval_queries.py` | `CreateQuery`, `EvidenceFeedback`, `_FEEDBACK_LABELS`, `PLANNER_VERSION`, `GENERATION_PROVIDER`, `GENERATION_MODEL`; `_idempotent_replay`, `_idempotent_store`, `_resolve_index`, `_insert_query`, `_insert_run`, `_accepted_body`; undecorated feedback handler body | 270–330 |
| `retrieval_run_store.py` | `_RunWriter`, `_persist_candidates`, `_context_tokens`, `_load_context_items`, `_numeric_from_fact_row`, `_persist_claims` | 300–350 |
| `retrieval_pipeline.py` | `_RunUsage`, `_parse_iso`, `_lane_query`, `_decision_dict`; moved `_execute_pipeline` body and one explicit `PipelineDependencies` record | 300–380 |
| `retrieval_reads.py` | `EVENT_SCHEMA_VERSION`, `MAX_TRACE_BYTES`, `MAX_EVENT_BYTES`; `_event_body`, `_trace_too_large`, `_trace_rows`, `_check_candidate_counts`, `_check_citation_count`, `_event_rows`, `_event_json`, `_format_cost`, `_group_candidates`, `_group_claims`; undecorated `get_query`, trace, and event-history handler bodies; one `TraceReadDependencies` record | 490–550 |

Keep these definitions physically in `retrieval.py`:

- `UnsupportedEmbeddingProvider`, `_resolve_embedding_provider`, `UnsupportedGenerationProvider`, `_resolve_generation_provider`.
- `_LANE_FUNCS`, `_HEARTBEAT`, `_STATEMENT_TIMEOUT`, `_COST_WARNING_HEADER`.
- `_lane_call`, `_corpus_read_connection`, `_failure_envelope`, `_run_pipeline_or_fail`, `_record_run_failure`, `_enforce_query_ceilings`.
- Complete `create_query`, `create_query_rerun`, `_sse_stream`, `stream_retrieval_run_events` bodies.
- Signature-preserving `_execute_pipeline` adapter and route adapters for `get_query`, `get_retrieval_run`, `get_retrieval_event_history`, `create_retrieval_feedback`.

The query module never calls the execution module. The store module never imports the facade or query module. Pipeline imports store types and immutable query constants if needed, never the facade. Reads imports neither pipeline nor facade. Facade imports helpers. No circular imports, late imports back into the facade, `sys.modules` lookup, dynamic `getattr`, `globals()` forwarding, or function-global rebinding.

## Preserve the actual patch/import surface

Repository searches inspected direct references and multiline monkeypatch calls, not only imports. Preserve these facade names and the consuming runtime paths:

| Existing patched name in `app.retrieval` | Required consumer resolution |
|---|---|
| `MockStructuredLLMProvider` | Retained `_resolve_generation_provider` resolves it from facade globals at each call |
| `_LANE_FUNCS` (setitem dense/lexical) | Retained `_lane_call` uses the same dict; never copy it |
| `_corpus_read_connection` | Retained `_lane_call` resolves the facade global when the lane callback runs |
| `_execute_pipeline`, `record_usage`, `_record_run_failure`, `tenant_connection` | Retained `_run_pipeline_or_fail` resolves current facade globals; failure path also retains current `record_usage` |
| `_run_pipeline_or_fail` | Retained create/rerun handlers resolve current facade global after admission commits |
| `_RunWriter`, `_resolve_generation_provider`, `_lane_query`, `execute_lanes`, `fuse`, `_persist_candidates`, `_load_context_items`, `_context_tokens`, `_persist_claims`, `settings` | `_execute_pipeline` adapter captures current facade bindings at each invocation in `PipelineDependencies` |
| `_trace_rows`, `_event_rows`, `_group_candidates`, `tenant_connection` | Trace route adapter passes current facade bindings in `TraceReadDependencies`; retained `_sse_stream` directly resolves current facade `_event_rows` and `tenant_connection` |

Existing direct imports/calls also include `_numeric_from_fact_row`, `_RunUsage`, `_check_candidate_counts`, `_check_citation_count`, `_sse_stream`, and `_execute_pipeline`. Keep those names with original signatures. `StructuredClaimGenerator.generate` and `MockCitationVerifier.verify` are patched on the actual external classes; import/reexport the same class objects, never wrap or subclass them.

Reexport every original named top-level class/function/constant from `app.retrieval` (explicit `as` aliases where lint requires), including helpers that are not currently patched. Define each class exactly once: e.g. `app.retrieval.CreateQuery is app.retrieval_queries.CreateQuery` and the corresponding store `_RunWriter`/pipeline `_RunUsage` identity must hold. Preserve external provider/retrieval class identity as well. Do not rewrite exception messages or Pydantic model fields/configuration.

### Pipeline dependency boundary

Use one frozen, explicitly typed dataclass in `retrieval_pipeline.py`, constructed inside the facade `_execute_pipeline` adapter. Fields correspond exactly to runtime call seams:

`run_writer`, `resolve_embedding_provider`, `resolve_generation_provider`, `lane_query`, `lane_call`, `execute_lanes`, `fuse`, `persist_candidates`, `load_context_items`, `context_tokens`, `persist_claims`, `settings`.

Use existing concrete result/argument types; callable fields may use `Callable[..., ExistingResult]` where the original heterogeneous callable has no narrower reusable protocol. Do not build a registry, service locator, generic context bag, or a hierarchy of protocols. `run_writer` is a factory callable, not a preconstructed writer. `settings` is a callable, not a snapshot of settings. `lane_call` is supplied from the facade so per-lane globals remain live inside the callback.

Mechanical changes allowed to the moved body: add one keyword-only `deps` parameter and replace the twelve corresponding global call references with `deps.<field>`. Preserve all existing arguments, keyword ordering where significant, local variables, branches, exception boundaries, event order and SQL call order. Other imported dependencies are the same objects/constants as the facade reexports; do not duplicate constants. Preserve the exact original `_execute_pipeline` facade signature and return value.

This is necessary because a mere reexport of a moved `_execute_pipeline` would retain the helper module's globals, bypassing ten existing facade patches. Do not capture dependencies once at import time or put callables in default argument values.

### Trace/read boundary

Use one frozen `TraceReadDependencies` in `retrieval_reads.py` with exactly `tenant_connection`, `trace_rows`, `event_rows`, `group_candidates`. The facade trace adapter constructs it per call, using the current facade names. Replace only those four global references in the moved trace body. All other bounded-read helpers stay in the same reads module; retain the existing raw contribution/citation preflights and runtime payload/collection caps.

For moved query-history and event-history bodies, pass `tenant_connection` as one required keyword-only callable. No dependency record is needed for a single dependency. The facade wrappers pass the current facade binding. The feedback body likewise takes this single connection factory; idempotency helpers remain colocated in the query module.

All four route adapters retain the original decorator, name, complete annotated signature, FastAPI defaults/aliases/dependencies, response object, and return type. Helpers are undecorated and receive ordinary parameters. Do not give FastAPI a new dependency-object argument. Keep router construction and registration order unchanged; `app/main.py` continues importing the same `app.retrieval.router` without edits.

## Nonnegotiable behavioral invariants

- No SQL string, SQL interpolation, parameter ordering, row factory, grant, role, transaction boundary, isolation level or statement-timeout change.
- Query/admission/idempotency commits still precede pipeline execution. Pipeline success and metering remain atomic; failures roll back then persist terminal failure and consumed provider cost in the fresh transaction. Never drop queued-run reservation accounting.
- Same immutable planner/provider/index/corpus pins, hashes, IDs, cutoff handling, Decimal conversions/formatting and numeric-provenance failures. No live-provider wiring.
- Same generation refusal/invalid-output/abstention behavior and citation integrity verification.
- Same event/state transition sequence and terminal-event-before-terminal-state update ordering.
- Trace raw ID checks stay before aggregation/sorting, within the existing repeatable-read/read-only snapshot; full payload/byte caps remain. No partial success.
- SSE retains lazy generator timing, first-batch preflight, connection closure before yield, 200-row batches, captured high water, Last-Event-ID semantics, heartbeat, cancellation, and late overflow transport failure. Do not replace generator delegation with eager materialization. Retaining `_sse_stream` verbatim is the simplest protection.
- Same HTTP status/body/header/error behavior, rate-limit decorators, auth dependency binding and uniform tenant 404s.
- All preexisting tests, fixtures/goldens, contracts, financial implementation, and migration files remain byte-identical.

## Implementation sequence and verification

### 1. Establish the final-main baseline and move storage helpers

- [ ] Create the issue branch/worktree from main containing #272's merge; verify exact allowed-path authorization and no active overlap with #61. Capture SHA, clean status, original top-level symbol inventory and file hashes for tests/goldens/contracts/migrations.
- [ ] Run existing retrieval/API/tenancy baseline with a private local PostgreSQL database and all migrations, requiring DB execution rather than silent skips. Record the one preexisting opt-in benchmark skip separately.
- [ ] Move query models/storage functions and run-store functions to the two named modules; add explicit facade reexports. Keep feedback handler on facade until the read/route-adapter step. Preserve ASTs and SQL bytes.
- [ ] Verify mechanical equivalence and existing focused tests before proceeding.

### 2. Move pipeline body while retaining controls

- [ ] Move `_RunUsage`, parsing/lane-query/decision helpers and the pipeline body. Add only `PipelineDependencies` plus the signature-preserving facade adapter described above.
- [ ] Keep provider resolvers, lane callback, pipeline transaction/failure functions and create/rerun route bodies in the facade.
- [ ] Compare the moved pipeline AST after undoing the exact `deps` substitutions and added parameter. Verify all unaffected moved definitions are AST-identical and all SQL constants unchanged.
- [ ] Run unchanged generation-runtime, metering, costs, API pipeline/citation and query-budget tests. Existing tests must prove facade patches still affect the moved body.

### 3. Move bounded reads and small handlers

- [ ] Move the exact reads inventory and add the trace dependency record/adapter. Move query-history/event-history/feedback bodies and add the four original-signature route adapters. Leave SSE generator and stream endpoint verbatim in the facade.
- [ ] Compare handler ASTs after reversing only explicit dependency-parameter substitutions; compare every original route decorator and signature against baseline.
- [ ] Run unchanged bound/reader/corpus/pagination/tenancy/OpenAPI-parity and retrieval tests, then the full API suite on the owned DB. Reader/corpus source remains untouched; these tests guard the integrated pin/cursor contract.
- [ ] Complete scoped lint/type/Bandit checks with the repository's existing settings. Do not suppress complexity/security/type failures or alter tests/configuration to make them pass.

### 4. Independent final mechanical and PostgreSQL review

- [ ] Reviewer independently inspects the equivalence checker instead of trusting its PASS. Require unchanged SQL literal sequences, unchanged decorators/signatures, complete class/function reexports, and no helper-to-facade imports or dynamic global tricks.
- [ ] Meaningful patch verification: run unchanged tests that pause `_execute_pipeline`, replace `_run_pipeline_or_fail`, fail `record_usage`, patch `_record_run_failure`, replace mock generation factories and pipeline helpers, mutate `_LANE_FUNCS`, wrap corpus connections, track `_trace_rows`/`_group_candidates`, and close the SSE generator. Existing mutation-oriented query-budget test must still fail for its deliberately bad lane then pass normally.
- [ ] Real PostgreSQL acceptance must cover rollback/failure metering, concurrent reservation admission, immutable query/rerun lineage, foreign-org access, dangling/cross-version citations, complete trace bounds (32k/32,001 contributions; 16k/16,001 citations), event replay beyond 2,000, first/later oversized event handling, cancellation, cursor/history traversal and the 51-run legacy 409/explicit-page case. Use existing tests; any additional reviewer reproduction stays in scratch, not the repository.
- [ ] Compare runtime OpenAPI and registered routes from baseline/final in separate processes: same paths/methods, response/status/header declarations, request schemas, aliases and dependency names. Exclude no functional fields to make comparison pass.
- [ ] Final diff must contain only the five approved source files. Tests/goldens/contracts/migrations and all non-retrieval source hashes match baseline. Record measured file sizes; prefer a small ~530-line exception over introducing another architectural layer.
- [ ] Only after independent review and current-head required CI pass should the lead merge and reconcile #196. No task-ledger change is part of this implementation.

Suggested focused commands (run from the future implementation worktree with its locked Python environment and private TEST_DATABASE_URL; FEL_REQUIRE_DB=1):

```sh
python -m pytest apps/api/tests/test_retrieval_api.py apps/api/tests/test_retrieval_generation_runtime.py apps/api/tests/test_retrieval_metering.py apps/api/tests/test_retrieval_costs.py apps/api/tests/test_retrieval_read_bounds.py apps/api/tests/test_tenancy.py apps/api/tests/test_openapi_parity.py -o addopts='--import-mode=importlib' -q --tb=short
python -m pytest apps/api/tests -o addopts='--import-mode=importlib' -q --tb=short
python -m ruff check apps/api/app/retrieval.py apps/api/app/retrieval_queries.py apps/api/app/retrieval_run_store.py apps/api/app/retrieval_pipeline.py apps/api/app/retrieval_reads.py
```

Use the repository's existing type/Bandit commands rather than inventing alternate configurations. Run full API once after the completed split; repeat only failures or checks affected by subsequent edits. This plan authorizes no new tests or dependency updates.
