# Financial Evidence Lab Backlog Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to execute one bounded issue at a time. The user explicitly requested parallel reviews; implementation remains constrained by path ownership.

**Goal:** Resolve every issue in the September 9 snapshot with testable implementation or verified acceptance evidence, and safely review, fix and merge the open PRs.

**Architecture:** Preserve the parent design and existing public contracts. Correct the current integration defects first, then complete deterministic correctness, live evidence, extraction review, modeling, forecasting and release in dependency order. Never replace the canonical task ledger.

**Tech Stack:** The approved stack is defined by `docs/decisions/ADR-0002-mvp-stack.md`; this plan introduces no stack change.

**Spec:** [Backlog resolution specification](../../research/2026-09-09-backlog-resolution-spec.md), subordinate to `specs/001-financial-evidence-lab/spec.md` and `plan.md`.

## Global constraints

- One issue and branch per worktree. Read current AGENTS.md, canonical artifacts,
  handoff and issue comments before claiming paths. Use the registered branch;
  a merged recovery branch is historical, so register a fresh residual branch.
- At most four agents, including the coordinator. Concurrent implementation
  may not overlap allowed-path globs, even if different files seem independent.
  Concurrent read-only reviews are permitted; integration is serialized.
- No new canonical task checklist. Issue references below are execution units,
  not alternative completion state for `T####` tasks.
- Accepted ADR, contract-change label and lead review for contracts/migrations;
  existing workspace-pin authorization rules apply to minimal security fixes.
- Tests precede behavioral fixes. Use exact current-source tests from the issue
  audit; prove the newly added regression fails before changing implementation.
- Decimal financial arithmetic, tenant isolation, immutable provenance and the
  specification's numeric gates remain mandatory. Mock-only evidence does not
  clear live gates. No paid call or hosted deployment is implied by this plan.

## Execution and evidence protocol

Each issue uses this sequence, with the concrete files and acceptance cases in
the [issue audit](../../research/2026-09-09-open-issue-audit.md) linked from the specification:

1. Fetch main and the issue; confirm dependencies' merge commits and exclusive
   allowed paths. Save baseline SHA and current acceptance text in the PR.
2. Reproduce the remaining behavior with its named unit, PostgreSQL, browser or
   evaluation test. For an acceptance-only issue, run the existing harness
   against the required environment and preserve its artifact instead.
3. Implement only that residual. Run its focused tests, format/lint/types and
   required generated-contract checks. If the contract changes, ship schema,
   client, fixtures, version and ADR together.
4. Independently review; push bounded commits and run CI against current main.
   Record passed, failed and skipped checks separately. Resolve verified
   findings, and repeat only affected validation plus mandatory CI.
5. Merge with the reviewed head guard, verify the merge result, attach evidence
   and close the issue only if every acceptance criterion is met. Reconcile
   handoff facts; only the lead updates canonical task completion.

Useful commands (run from the isolated issue worktree):

```sh
git fetch origin
gh issue view ISSUE --repo wilsonhj/financial-evidence-lab --comments
git diff --check
pytest PATH_TO_THE_ISSUE_TEST_MODULE -q
pnpm --filter @fel/contracts check:generated
gh pr checks PR --repo wilsonhj/financial-evidence-lab
gh pr merge PR --repo wilsonhj/financial-evidence-lab --squash --match-head-commit REVIEWED_SHA
```

The uppercase operands are command parameters supplied by the specific issue
entry, not permissions to select unrelated scope. Database tests must use an
isolated test database with the migration ledger applied; never use production.

## Wave 0 — complete the current integration

**Issues:** #249, #191, #193, #203, #188; #252 security advisory remediation.

**Files:** #250's runtime pins; `apps/api/app/ratelimit.py`,
`apps/api/app/observability.py` and their tests; retrieval `verification.py` and
generation tests; contracts/version/generated client; ADR-0015 and API contract
decision record; handoff and these planning documents.

**Sequence:** review #232/#241 concurrently, review #250/#251, merge #250, land
the separate minimal security PR if the current advisory gate fails, then merge
#232 at 0.5.0 and #241 at 0.6.0. Publish the final reconciliation through #251.
Do not merge #251's stale descriptions of gates after those gates changed.

**Required regression examples:**

```python
# The authenticated dependency must spend the same organization's bucket.
dependency(TenantContext(canonical_uuid, user_uuid, "owner"))
with pytest.raises(HTTPException) as error:
    dependency(TenantContext("{" + canonical_uuid.upper() + "}", user_uuid, "owner"))
assert error.value.status_code == 429
assert error.value.headers == {"Retry-After": "1"}

# Test through structured generation, not only direct verifier construction.
# source=-100/text=+100; source='did not grow'/text='did grow'; reordered
# subject/object; and correct numeric metadata accompanying wrong prose.
assert verified.status not in {"supported", "derived"}
assert verified.confidence < Decimal("1")
```

**Integration proof:** invalid generation must persist safe usage and typed
abstention while final actual spend and terminal state commit atomically.
Test transient and persistent metering errors as well as contract failure.
All existing 402/429 responses survive generated-client regeneration at 0.6.0.

The session completed #250 (`9e59edb`), #253 (`3dfe678`), #232 (`eb8b7c8`)
and #241 (`5e1faa6`) with final CI passing. #251 publishes this audit and plan.
The remaining waves describe work still to execute, not completed changes.

## Wave 1 — stable tests and deterministic correctness

**Issues:** #248, #230, #221, #153, #154, #137, #194.

Run #248's API test work beside #230's ingestion-test work only after narrowing
and registering disjoint allowed paths; otherwise serialize the broad worker
globs. Keep #221, #153, #154 and #194 sequential where extraction paths overlap.

- #248 separates deterministic endpoint behavior from a reference-profile
  latency benchmark. Assert a query-count/operation-budget invariant for the
  functional test, including an injected extra-query regression; retain the real
  performance target in a dedicated benchmark rather than raising a timeout.
- #230 waits a bounded interval to observe lock contention. On timeout, emit
  the warning required by the issue, visible under pytest -q, then release the
  blocker and finish cleanup. A hard failure needs measured justification and
  updated acceptance. Retain
  database-scoped lock filtering and clean up both connections on failure.
- #221 corrupts a stored output/hash, uses a deliberately non-deterministic
  provider for recovery, restarts the store, and proves the new durable output
  is loadable without another provider call. Update step output/hash atomically;
  do not reintroduce event-payload checkpoints superseded by migration 0006.
- #153 defines one unit canonicalizer across normalization, identity,
  duplicates and definitions; test case-equivalent units and distinct currencies.
  Persisted identity changes require collision/migration analysis in the ADR.
- #154 tests known-polarity and free-text guidance ranges, signed bounds,
  floor/ceiling and preserved source values. Use the approved ordering semantics
  across normalization and validation rather than comparing raw magnitudes.
- #137 distinguishes refusal from insufficient evidence, preserves response/
  model/config and estimated/actual cost provenance, and tests genuinely missing
  evaluation value/lineage/range/scale invariants. Do not reimplement the already
  required `supports` argument or existing model status guards.
- #194 resolves the unreachable tool interface with explicit per-role dispatch
  or a documented no-tool provider mode. Forbidden tools and bounded calls must
  be tested. Preserve already wired cancellation and nullable unscored confidence.

**Exit:** regression failures become passes and survive real PostgreSQL restart
where applicable. No live model is needed for these deterministic fixes.

## Wave 2 — operational and API residuals

**Issues:** #191, #190, #200, #203, #196.

Finish #191 after #232/#241: design cursor pagination and reader-size behavior
with API, contract and HTTP client together. Test >200 rows, newest and oldest
record reachability, equal-time cursor tie breaks, tenant/as-of filtering,
idempotent traversal and a reader exactly at/over the documented limit. Preserve
all existing content until the client can retrieve every page. Add pool overload
backpressure and reservation reconciliation only as explicitly scoped residuals.

#190 verifies `fel_worker` role selection in deployed configuration, forbidden
DDL and ordinary worker writes under the least-privilege role, including pooled
session reset. Retain separate migration credentials. #200 locks the actual
runtime dependency closure, verifies dev tools do not ship, and configures the
existing worker health endpoint in the deployment manifest. Do not remove an
already absent `httpx2` dependency. #203 measures coverage before setting a
documented floor, makes required checks machine-readable and verified against
repository settings, tests Sentry initialization/privacy and browser-cache keys,
and records real maintainers instead of inventing CODEOWNERS identities.

Perform #196 only after retrieval and extraction behavior stabilizes: move
persistence/serialization behind existing interfaces in separate small PRs,
keep routes/FSM control thin, compare before/after contract and crash-resume
behavior. No new framework or generic repository abstraction is required.

**Exit:** new API behavior is both declared and reachable; runtime/DB evidence
matches deployed settings; CI checks do actual work with expected test counts.

## Wave 3 — live corpus, provider and reader evidence

**Issues:** #195, #177, #81, #56, #201, #132, #108, #96, #87.

Start mock adapter contract preparation while awaiting secrets. #195 must expose
a narrow structured-output adapter with bounded time/tokens, refusal/error and
usage metadata, and fail-closed provider selection. OpenAI can proceed under
the accepted baseline; any substitution needs its benchmark-backed ADR.

#81 recovers or rebuilds the missing checksum-pinned stress manifest and proves
at least eight distinct stress features. #177 provisions named credentials,
resolves corpus sources, runs repeated predeclared embedding comparisons under
the 512-dimension constraint, and stores immutable configs/usage/results. #56
then proves 20 issuers/eight years and stable hashes/idempotence. #132 also owns
  the live semantic-verifier integration in `packages/retrieval/**`, using #195
  provider transport: test generated paraphrases, sign/negation contradictions,
  refusal/timeouts, budget and redaction, then measure entailment precision at
  >=95%. This is necessary because #241 deliberately retains a conservative
  lexical mock. Register the scope before dispatch. #201 executes
the real gate over the built index; #132 completes the 65-question live report.
If Recall@10 fails, use the accepted top-100 reranker trigger before index
redesign, and preserve the failure while fixing it.

Before #108, register separate lead-owned prerequisites for the web integrity
error mapping and `infra/railway/web.json`; the smoke issue may not absorb
product fixes outside its scope. Once those merge, #108 configures the isolated
hosted HTTP reader and proves
worker → PostgreSQL → API → production browser against pinned document versions.
Test authentication, citations, ETag/304, missing/integrity cases and tenant
isolation. #96 and #87 close only after their remaining hosted criteria pass.
No fixture-only E2E or SSO redirect counts as hosted reader acceptance.

**Exit:** immutable live M1/M2 reports meet all applicable gates; credential and
deployment blockers are explicit until actually satisfied.

## Wave 4 — extraction review and confidence

**Issues:** #61, #135, #62; epic #6.

Build #61 against accepted extraction contracts, migration 0006 and terminal-run
semantics already merged. Test accept/edit/reject/merge/rerun, authorization,
version conflicts, immutable approved records, correction history and attribution.
Ship API and web review behavior together. #135's same-origin SSE proxy forwards
authentication safely, honors Last-Event-ID, sends 15–30 second heartbeats and
stops/reconnects cleanly without duplicating durable events. It must never emit
raw checkpoint outputs or cause a terminal run to resume.

#62 follows #61 and live-cutover evidence: calibrate on held-out labels, record
calibration version, enforce 0.85/0.80 thresholds and never auto-approve money,
guidance or assumptions. Test owner-only audited threshold edits and invalid/
conflicting records regardless of confidence. Execute extraction and numeric
gates plus live structured-output smoke before declaring M3 complete.

## Wave 5 — model persistence and product workflows

**Issues:** #219, #197, #64, #65; epic #7.

#219 first records separate AST and iteration dispositions. The default plan
implements the current parent requirements; any deferral or amendment needs an
accepted scope decision. Extend the existing Decimal engine rather than
rebuilding #63. For each retained clause, implement safe formula
AST, typed operations, dependency extraction, rejected undeclared cycles and
explicit iterative groups with bounded iterations/tolerance/non-convergence.
Test illegal syntax, unit/period mismatch, deterministic recalculation and
5,000-node performance. No Python `eval` or model-generated authoritative math.

Land scoped #197 model storage contracts before #64 consumes them: tenant keys,
immutable versions, sparse scenarios and a valid tenant-scoped active-scenario
reference. Forecast tables belong to #66's contract slice, not empty speculative
tables. Test migration/restore, RLS, cross-tenant references and historical
immutability. Do not modify applied migrations to add the new tables.

#64 attaches only approved extraction versions, preserving source/cutoff/unit
lineage; bull/base/bear overrides never mutate reported history. #65 consumes
the resulting interfaces for graph, bridges, waterfalls, sensitivities,
formula/lineage/diff/restore views. Test coordinated updates, keyboard access,
chart semantics and restored model identity. #64 waits for confidence controls;
frontend fixtures may be prepared earlier only under stable approved contracts.

M4 product completion requires the prior live milestone exits even when
deterministic implementation is prepared earlier.

## Wave 6 — forecasting, backtests and audited release

**Issues:** #66, #67, #68; epics #4–#8 and umbrella #188.

#66 defines the immutable forecast run/fit/predict/backtest contract, then ships
last-value, seasonal-naive and analyst-driver lanes for quarterly revenue, ARR
where disclosed and gross profit. Record 1–8-quarter horizons, training windows,
cutoffs and input versions; short histories abstain or disclose the limitation.
#67 uses rolling origins with vintage-aware features, horizon-specific metrics
and calibrated 50/80/95% intervals. Test look-ahead leakage, empty/zero target
denominators, deterministic repeat runs and non-default advanced models that
fail the seasonal-naive gate.

September 11 source preflight found only a forecasting placeholder, with no
frozen forecast HTTP/storage interface. ADR-0023 therefore requires a separate
lead-owned contract/API/migration prerequisite before #66's implementation;
its current feature allowlist is not permission to edit those shared paths.
Resolve and record these concrete domain choices at that freeze:

- Pin the immutable truth/restatement vintage used for backtest labels separately
  from training inputs, so reruns cannot silently acquire later corrections.
- Specify interval calibration method, minimum samples and exact paired
  median-MAE aggregation; retain existing release thresholds and short-history
  abstention rather than selecting favorable samples after seeing results.
- Map ARR explicitly: the ontology treats it as instant USD/year, so quarterly
  forecast periods or annual rollups must not silently sum it like revenue.

The current market adapter's day/adjustment fields do not supply an as-of vintage
contract. Baselines need not acquire external features implicitly; any future
feature requirements must specify point-in-time availability and its proof.
These are unresolved design inputs, not authorization to extend the adapter,
change financial semantics or bypass #64/#62 and live-release dependencies.

#68 traverses source → approved extraction → model → forecast → export with
hashes and versions intact. Generate Markdown/PDF, CSV/XLSX, JSON evidence and
workspace manifests. Freeze/adjudicate >=300 questions, run every numeric gate
plus security/accessibility/load/restore/provider-failure/browser suites, then
sign the immutable release report/artifact. No release when a gate fails.

Close epics by milestone evidence, not issue counts: #4 needs corpus+reader;
#5 retrieval/live claim gates; #6 review/calibration; #7 scenario/model UX;
#8 backtests+release. #188 closes only when each review finding is resolved or
explicitly transferred with acceptance and traceability.

## Safe parallel dispatch

The initial parallel review is an exception to implementation ownership because
reviewers read isolated snapshots. Subsequent workers use the existing package
graph plus path exclusion; a later wave is not a blanket four-agent dispatch.
Examples after dependencies clear: platform runtime work can accompany
calculation-engine tests only if neither claims shared configuration; provider
mock work can accompany web fixture preparation under frozen contracts. Any
shared contract, migrations, root configuration or broad `workers/tests/**`
ownership is serialized. Keep the coordinator slot available for integration.

## Final verification of this plan

Compare all 40 session issue IDs (39 initial plus #252) in the dated audit against this plan's waves and epic
closure rules. Re-query GitHub after merges; record newly discovered issues and
PRs separately. Confirm each relative document link resolves, workstream IDs
are unique, dependencies resolve and the graph is acyclic. Do not interpret
this plan's publication as acceptance of the live release or completion of its
implementation work.
