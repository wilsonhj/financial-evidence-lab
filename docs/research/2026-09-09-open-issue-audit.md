# Financial Evidence Lab: live issue audit, 2026-09-09

Read-only audit for integration lead. Snapshot: 39 open issues fetched with bodies/comments from GitHub, initial inventory recorded by the 39 numbered issue sections below. Source baseline `75fad38`, then `9e59edb` after this session's PR #250 merged. #249 is therefore resolved in-session; final live count must be refreshed. Local working checkout was older and was NOT treated as trunk. PR #251's proposed reconciliation was read as proposed, not merged. No implementation tests were executed by this audit; source checks and merged history underpin findings.

## Governing sources and scope

`AGENTS.md`, constitution 1.2.0, canonical `specs/001-financial-evidence-lab/{spec,plan,tasks}.md`; subordinate specs 002/003/004/005; ADR-0002 accepted, ADR-0011 accepted, ADR-0012 Proposed; GitHub issue comments only where compatible with trunk. No second T#### completion ledger. A completion spec may map issue IDs to criteria and reference canonical task IDs without reproducing task checkboxes.

One issue + branch + worktree per implementation; disjoint allowed paths, at most four packages. Shared contract/migration/spec/ADR edits require contract-change + accepted ADR + lead review; pure ledger state/annotation changes have the narrower no-ADR exception. Proposed new owned paths below need durable lead registration before dispatch; this audit does not authorize them.

## Verified corrections that materially change the plan

1. #177/#188 comments declaring live adapters, accepted ADRs and full coverage describe an abandoned branch, NOT main. Main has only mock providers; ADR-0012 is Proposed; CREDENTIALS.md still says Not requested. Do not treat provisioning alone as the remaining code work.
2. #221 remains a durability concern, but #236 changed the storage model: `PostgresCheckpointStore.load_succeeded` reads `output` and `output_hash` directly from the step row. `_insert_step_row` still uses `ON CONFLICT DO NOTHING`. Reframe repair around atomically advancing the existing succeeded row's output/hash/usage and testing a fresh-store resume, not reconstructing event selection. Verify whether deterministic corrupt-row recovery is also affected; the old "unreachable until nondeterministic provider" assertion is no longer proven after #236.
3. #194 cancellation already reaches handlers through the consumer's bound `queue.is_cancel_requested` callback. NULL confidence and blocker-derived priority landed #240. Remaining work is deciding and implementing actual bounded tool execution or explicitly removing/defer-documenting unused declarations. Removing promised allowlisted-tool functionality requires consistency with canonical requirements, not silent deletion.
4. #200 has NO remaining httpx2 occurrence on main. Runtime/dev split exists. `health.py` exists but Railway `worker.json` has NO `healthcheckPath`; comments claiming it is deployed are false. Remaining: reproducible hashed dependency resolution, audit actual installed application/first-party dependency closure, wire deployed worker health and verify recovery. `infra/railway/README.md` still claims consumer has no HTTP surface.
5. #190 role/migration exists but opt-in role configuration is absent from deployed worker config. Keep open for enforced rollout plus stale README correction and real role-path proof.
6. #137 `build_gate_report(... supports: dict[str,int])` is already mandatory. Claim/citation status invariants exist in retrieval models. Re-scope remaining refusal/cost provenance and only genuinely missing eval-model invariants; do not reimplement completed items.
7. #201 CLI and golden exist, but recall is 0.4692 vs required 0.90, and CI does not enforce full quality. Do not lower canonical release threshold or relabel a passing subset as full acceptance. Separate deterministic mock regression CI from credentialed full quality gates; a subset needs explicit non-release identity and cannot close full benchmark acceptance.
8. #108 still needs its dedicated web integrity-classification fix and `infra/railway/web.json`. Issue addendum already authorizes fixture transport, mock identity for this isolated smoke, same-service API/storage topology and workflow scope; avoid reopening settled decisions. Smoke mock-auth exception is not production authentication acceptance.
9. PR #251's new registrations are a starting point, not sufficient authorization for all residuals: #195 omits actual API/worker provider-factory wiring; #197 omits design/contracts ownership; #203 omits root Python/JS coverage configuration and worker tests; #201 lacks explicit CI shared path. Correct at dispatch. #108 cannot silently absorb product fixes.
10. #219 AST/iterative clauses are unresolved product requirements even though #63 engine package merged. Two recorded rulings are necessary before #7 closes.

## Global acceptance gates

Every issue closes only on merge plus its acceptance evidence, or an explicit reviewed scope disposition; epic/tracker closure follows children, not code duplication. Package checks: relevant regression/contract/DB harness/browser checks, telemetry where relevant, docs, independent review, required CI. Use real Postgres with fail-closed DB-test environment; new durable suites need isolated sibling databases.

Parent §19.6 release thresholds stay: temporal validity 100%; numeric value/unit/period/sign/scale >=99%; citation entailment >=95%; citation completeness >=92%; Recall@10 >=90%; guidance F1 >=90%; KPI/driver F1 >=88%; contradiction recall >=90%; unsupported-answer abstention precision >=95%; 80% interval coverage 75–85%. Advanced models must beat seasonal-naive median MAE over horizons 1–4, otherwise remain non-default. M2 uses 50–100-question smoke (65 currently); M5 frozen >=300 dual-adjudicated questions. Parent §16 reference load: 25 concurrent users; reference corpus 100 issuers/eight years/10m passages/15m embeddings; 5k-node recalculation <500 ms p95. Do not mistake loaded-host functional timing for that benchmark.

## Issue-by-issue disposition

Priority: P0 prevents unsafe live cutover or financial-integrity failure; P1 blocks a milestone/release or closes material acceptance gap; P2 maintenance/design cleanup that still must be resolved for zero open issues. Owned paths below are proposed concrete dispatch bounds; existing issue bounds remain controlling until explicitly updated.

### #4 — M1 epic — P1, tracker

Remaining: #56 live 20-issuer/eight-year corpus artifact, #81 stress coverage, #87/#96/#108 production-reader evidence. Existing ingestion/parser/UI package code merged. Owner: integration lead, `docs/handoff/{STATUS.md,workstreams.yaml}`, canonical ledger state/annotations only. Close when live source/span hashes stable across idempotent reruns, temporal validity 100%, adjusted-market-data guard evidence and M1 gate pass; then close child trackers and update lead-owned task state. Credentials inherited from #177/#108.

### #5 — M2 epic — P1, tracker

Remaining: #193 real claim-output path, #132 full live gate, #137 residual provenance/invariants, #201 enforcing CI and T0215 reference retrieval performance. #135 is explicitly M3 and does not gate M2. Rename stale Atlas title; Atlas T0211–13 remains deferred, no implementation required. Same lead ledger paths as #4. Close only frozen smoke five metrics plus contradiction/abstention evidence as applicable, immutable replay, and reference/performance acceptance; no closure from mock plumbing alone.

### #6 — M3 epic — P1, tracker

Remaining: #61/#62 and integrity/live prerequisites #153/#154/#194/#221/#195, #135 integration. #60 core merged, #146 terminal semantics and #157 step-output migration merged. Same lead ledger paths. Close when extraction gates pass, monetary facts, guidance and assumptions never auto-approved, with stable evidence and immutable correction history, resumable metadata-only SSE, and live provider failure/smoke evidence; #62 must consume M2 contradiction report.

### #7 — M4 epic — P1, tracker

#63 engine merged, ledger reconciliation still lead-owned. Remaining #197 schema design/contract, #219 clause rulings, #64 model seeding/scenarios, #65 graph/charts/history. Close on approved records-to-model without retyping, immutable reported history, diff/restore, 5k-node p95 <500 ms evidence and explicit AST/iterative disposition. No provider credentials for deterministic implementation.

### #8 — M5 epic — P1, tracker

Remaining #66/#67/#68 and #177 live corpus/provider deployment prerequisite. Same lead ledger paths. Close only complete §26 user journey, >=300 frozen dual-adjudicated benchmark, every §19.6 gate, security/a11y/load/restore/cost/provider-failure/E2E and signed immutable release artifact. Atlas/analogue deferrals stay excluded; stale analogue prose in #66/T0507 requires explicit scope clarification, not unrequested implementation.

### #56 — live corpus artifact — P1, evidence-only residual

PR #86 delivered harness and T0111. Remaining exact recipe `evals/reports/corpus-qa/SCHEMA.md` on fresh dedicated DB, real SEC egress, `FEL_SEC_USER_AGENT`, <=2 requests/sec; commit `*-live-cohort.json` with `acceptance.accepted=true` and `span_hash_verification_rate="1.000000"`. Paths `evals/reports/corpus-qa/**` (broader existing `evals/**`, `workers/tests/**` only if genuinely needed). Dependency #177 provisioning and real pinned sources. Close on lead verification of report for 20 issuers/eight years; no harness rewrite.

### #61 — review API/UI — P1, implementation

Old #146/#157 gates cleared; serialize after #232/#241 release `apps/api/**`. Paths `apps/api/**`, `apps/web/**`. Implement generated-contract run create/list/get/cancel/rerun, atomic accept/edit/reject/merge/bulk, immutable approved corrections/history, SSE, accessible review/execution UI. No manual TS mirrors. Tests: RBAC, tenant-hidden 404, as-of, stable cursor ordering, Idempotency-Key, per-proposal expected-version batch atomicity, If-Match concurrent correction one commit/one412, merge identity/evidence, blockers prevent approval, SSE replay/redaction, keyboard/browser. Coordinate #135 same-surface delivery without concurrent owners. No credentials for fixture work; contract changes separate accepted ADR.

### #62 — calibration/extraction gates — P1, implementation/live evidence

Depends #61, #153/#154 correctness, #221 replay, #195 adapter, #177 provisioned live flow. Existing bounds `workers/src/fel_workers/extraction/**`, `workers/tests/**`, `evals/**`; adapter remains #195 owned. Build versioned adjudicated isotonic-v1 artifact (all hashes, breakpoints/counts/ECE/Brier), bounded owner-audited 0.85 record/0.80 field policy, exhaustive no-auto-approval proof through API/bulk/worker/replay/policy. Resolve unscored NULL (#240) vs older insufficient-data zero/high semantics explicitly: preserve distinction between absent scoring and a scored fail-closed result. Gates guidance>=90%, KPI/driver>=88%, numeric>=99%, temporal100%; link M2 contradiction. Credentialed OpenAI smoke remains accepted baseline unless specification amended after ADR evidence. Close on immutable live/eval report, provider-failure suite, all acceptance.

### #64 — approved facts/scenarios — P1, implementation

Depends #63 merged, #62 gate, #197 M4 persistence contract and #219 scope ruling. Paths `packages/calculation-engine/**`, `apps/api/**`; database/schema/client changes belong serialized #197 contract phase. Map approved immutable extraction versions to source nodes, sparse bull/base/bear overlays, workspace-scoped persistence and audit. Tests monetary approval cannot be bypassed, evidence survives mapping, scenario overrides never mutate reported history, tenant/cutoff boundaries, deterministic replay and sparse overrides. Close when approved facts seed/recalculate correct persisted model without re-entry.

### #65 — model UI — P1, implementation

Depends #64; serialize against #66 shared UI. Paths `apps/web/**`, `packages/ui/**`. Implement driver graph, history/forecast coordinated charts, price-volume-mix bridge, revenue/GP waterfall, heatmap/tornado, formula/dependency/assumption/citation/diff/restore. Use existing ECharts/React Flow; no new stack. Tests known Decimal results displayed accurately, graph keyboard table equivalent, linked evidence, scenario immutability, version diff/restore browser journey, WCAG. Close on all views + end-to-end model journey; fixture credentials only.

### #66 — forecasting — P1, implementation

Depends #64 plus #197 forecast contract. Paths `workers/src/fel_workers/forecasting/**`, `workers/tests/**`, `apps/web/**`, `packages/ui/**`; contract changes separately authorized. Implement immutable run fit/predict/backtest interface, last-value/seasonal-naive/analyst-driver forecasts, 1–8-quarter horizon comparison/contributions/uncertainty. Analogue lane stays deferred despite issue body. Tests quarterly fiscal/units/Decimal identity, cutoff-safe features, immutable run pins, baseline correctness, UI equality to stored outputs. Close interface and forecast lab, with intervals/backtests delegated #67.

### #67 — backtests — P1, implementation

Depends #66. Paths `workers/src/fel_workers/forecasting/**`, `workers/tests/**`, `evals/**`. Implement rolling-origin horizon1–8, 50/80/95% intervals, calibration/error reports; known publication/vintage/corporate-action inputs only. Tests no lookahead across every origin, held-out calibration, 80% coverage75–85%; advanced-model default only after lower median MAE than seasonal-naive over1–4. Close reproducible reports + selection guard, then #68.

### #68 — audited release — P1, broad package split into sequential checkpoints on same issue

Depends #67, #65 user-facing completeness, #177, prior epic acceptance. Paths `apps/api/**`, `packages/export/**`, `evals/**`, `docs/release/**`; any deployment/shared CI work needs explicit ownership. Deliver full source→fact→model→forecast→export traversal; Markdown/PDF, CSV/XLSX, JSON bundles and workspace manifest. Explicitly cover FOR-004 reported/modeled/user-supplied distinctions (unallocated citation gap). Freeze >=300 dual-reviewed questions and immutable protocol, run all numeric and §26 gates, security/RLS/injection, restore, load, browser/a11y, costs, provider faults. Close signed content-addressed release+evaluation bundle; qualified adjudicator staffing/paid-provider budgets needed by #177. Do not omit #65 merely because old graph lacked its dependency.

### #81 — SEC stress dataset — P1, research/data implementation

Recover and verify base60 manifest from `agent/ext-sec-fixtures`/retired integration history; it is absent on main, so additive supplemental work cannot assume it exists. Never merge retired integration trunk wholesale. Paths only `evals/datasets/sec-fixtures/**`. Real SEC egress compliant identity<=2/sec. Select3–6 noncohort issuers from fetched discovery evidence; checksum bytes, tag only byte-proven features; canonical20 issuer file unchanged. Gate combined >=8 distinct stress features; document synthetic fallback for unfound structural cases. Dependency #177 SEC access, no merge-code dependency. Close verified manifest+README and executable validation.

### #87 — reader integration parent — P1, tracker

Children A–E shipped, production-path residual #108 remains; #96 is tracker. No repeated implementation. Lead ledger paths; close after #108 hosted artifact passes and #96 criterion11 signed off. Preserve ADR-0005 pinning/anti-oracle/canonical spans. Same credential gate as #108.

### #96 — cross-stack residual — P1, tracker

Criteria1–10 shipped PR #105 with synthetic/CI stack; criterion11 exclusively #108. Existing `evals/**` ownership must not redispatch. Close only after #108 real worker→Postgres→FastAPI→real HttpEvidenceSource→production browser artifact; lead references it and then #87 can close.

### #108 — hosted reader smoke — P1, implementation plus hosted evidence

Dependencies #105/#99/#106 merged; outstanding dedicated integrity-kind web fix, lead-owned `infra/railway/web.json`, provisioned isolated smoke environment. Existing paths `evals/**`, `apps/web/**`, `apps/api/**`, `workers/**`, named `.github/workflows/reader-prod-smoke.yml` authorization in comment; infrastructure fix separate path ownership. Implement approved third `FEL_FIXTURE_INGEST` transport through real consumer/parser/storage, mock-auth tenant bootstrap (not evidence SQL seeding), colocated worker/API storage, production Next.js separate service. Test all ten issue criteria: canonical nonfirst highlight, storage-byte tamper integrity-alert/no quote, future==missing404, ADR0005 pin/amendment resolution,401/403/500/502/503 typed errors, repeatability. Hosted screenshots/logs/traces Actions artifact + committed digest/two screenshots. Secrets by name only: DB/storage/fixture paths, auth, web source/API URL/token/entities + environment workflow secrets. Product defects stop/escalate into dedicated owner, never hide fixes inside smoke.

### #132 — full65 live retrieval gate — P1, live code/evidence

Depends #193 real output/verifier, #195 accepted baseline adapter, #221 safe replay, #177 real corpus/provisioning, #137 provenance and #201 executable CI. Paths `evals/**`, `packages/retrieval-evals/**`, `packages/retrieval/**` as needed; factory/contract changes belong owners. Pin actual EDGAR documents and resolved manifest; predeclare repeated-run protocol; benchmark approved baseline and only authorized competitors at512 dimensions; record per-question outputs, citations, hashes, settings, latency/token/cost. Own live semantic-verifier integration in packages/retrieval using #195 transport: test paraphrase support, sign/negation contradictions, refusals/timeouts, redaction and budgets; measure >=95% entailment precision rather than treating lexical identity as semantic verification. Register that residual scope before dispatch. Five exact thresholds above; contradiction/abstention reports also needed for complete M2 release claims. T0215 exact-vs-HNSW latency/ref-corpus suite assigned here explicitly (older #137 attribution otherwise owns no such checklist). Executable documented runner and protected CI quality gate. Model substitutions require ADR benchmark evidence; don't assume stale named models available. Close real65 passing report plus signoff, not mock golden.

### #135 — mounted live SSE — P1, M3 integration slice

Existing parser/reconnect tested, M2 stored replay sufficient. Paths `apps/web/**`, `apps/api/**` if server contract integration necessary. Depends async review runs #61 and metadata-only #157 merged. Implement same-origin authenticated streaming proxy+consumer; handle Last-Event-ID, CRLF/chunk boundaries, reconnect/abort, no leaked step output, terminal state, missing/tenant/cutoff errors. Coordinate one owner with #61: separate sequential child delivery/PR or explicitly shared acceptance, never concurrent overlapping worktrees. Close browser proof of actual incremental events, not snapshot replay. No live provider secret needed with bounded fixture run.

### #137 — cutover hygiene — P2, partial

Required supports already fixed; claim/status invariants partly already exist. Paths `apps/api/**`, `packages/retrieval/**`, `packages/retrieval-evals/**`; serialize after #232/#241. Verify and add distinct provider_refusal telemetry, response/model/config and estimated/actual cost audit provenance, missing eval value/lineage/range/scale invariants. Tests refusal != insufficient evidence, cost writes not merely reads, invalid constructors fail, mandatory empty supports fail closed. Close checklist with exact shipped evidence for already-done portions plus new residual tests; no implicit ownership of T0215 unless issue amended.

### #153 — canonical units — P0 before extraction gate, design+fix

Paths `workers/src/fel_workers/extraction/normalize/**`, `.../validate/**`, `workers/tests/extraction/**`, `packages/ontology/**`; any contract/migration/ADR paths require explicit registration. Decide canonical vocabulary/case semantics and versioned proposal/conflict identity compatibility; do NOT globally uppercase arbitrary Unicode issuer units. Apply consistent comparison across _facts/_context/comparability_key_for/_unit_errors. Tests USD/usd identity mismatch AND duplicate/conflict detection, distinct unit noncollision including Unicode, ontology definition consistency, persisted replay stability; replace known-gap test. Close accepted ADR plus all regression evidence before #62.

### #154 — guidance bounds — P0 before extraction gate, design+fix

Same extraction normalize/validate/test paths; ADR/contracts if semantics change. Decide numeric-bounds vs stated-order and proposal-id versioning. Implement consistently for ontology and free-text metrics; preserve provenance/raw order and handle negative parentheses after sign normalization. Do not `abs()` or blindly swap malformed positive inversion into acceptance: define how valid stated-order vs extraction error is distinguished. Tests both negative orders and positive inverted free-text revenue/operating_income/net_loss, persisted IDs/history. Close accepted semantics+all tests before #62.

### #177 — cutover orchestration — P0, prerequisite/evidence owner

Paths existing `evals/**`, `workers/tests/**`, `docs/handoff/CREDENTIALS.md`; providers/factories/contracts/infra not silently in scope. Depends #195 adapter, #193 claims, #191 limits, #190 effective worker role, #221 replay, #200 deploy readiness, #137 hygiene; coordinates #56/#81/#132 while each issue retains narrow acceptance. Approved OpenAI baseline needs no substitution ADR; Anthropic or new embedder requires benchmark evidence and accepted distinct role ADR (0012 currently only generation). Credentials by approved secrets manager: Supabase URL/public/service key, FEL_OPENAI_API_KEY, FEL_ALPHA_VANTAGE_API_KEY, FEL_SENTRY_DSN, FEL_SEC_USER_AGENT; optional competitor secret only once authorized. Budget authorization per current accepted market-data ADR; staff two qualified benchmark adjudicators. Close all live reports and deployment readiness, not provisioning checklist alone. Serialize evals/workers tests with #62/#66/#67/#68/#108. Add #62 live dependency to graph when lead approves; #177 must not depend on completed #62 or create circularity.

### #188 — architecture umbrella — P1, tracker

Resolved children #189/#192/#198/#199/#202 etc have merged evidence; remaining live children #190/#191/#193/#194/#195/#196/#197/#200/#201/#203. Lead ledger paths only. Close when every child accepted or explicitly transferred residual to named open milestone with scope/owner; zero-backlog goal still requires transferred issue resolution. Branch-only historic claims are not acceptance. Refresh stale measurements instead of quoting old code/test counts.

### #190 — effective worker least privilege — P0 before deploy

Migration0008/role adopter shipped #238. Paths `infra/railway/worker.json`, `infra/railway/README.md`, `workers/src/fel_workers/storage.py` only if fail-closed config required, `workers/tests/**`, `db/migrations/README.md`; migration/harness only if role gaps discovered, accepted ADR/lead ownership. Set supported deployment environment mechanism for FEL_WORKER_DB_ROLE=fel_worker (do not invent Railway JSON env keys); separate migration-owner connection from runtime. Gate real ingestion/retrieval/extraction/queue paths under role, forbidden DELETE/DDL and tenant leakage, production effective current_user proof with secrets redacted. Close deployed rollout plus corrected no-service-role README, not opt-in unit tests.

### #191 — API boundedness/costs — P0 before paid provider, partial PR #232

#232 owns budgets/rate-limit/pool/API Sentry + additive contract; root reviewer decides merge. Remaining after it: bounded list pagination and bounded reader spans/facts/siblings. Paths `apps/api/**`, `packages/contracts/**`, `docs/handoff/CONTRACTS.md` and accepted ADR for pagination/truncation; avoid silent truncation or dangling citations. Tests budget rejects BEFORE provider, concurrent requests cannot over-reserve, replay not double-charged, 429 Retry-After; page default/max/cursor stability and cross-tenant/as-of; oversized reader typed closed failure or explicit coherent truncation per frozen contract. Close all endpoints bounded and cost/rate evidence. PR merge alone may leave issue open.

### #193 — consume structured claims — P0 before live, PR #241

Paths `packages/contracts/**`, `packages/providers/**`, `packages/retrieval/**`, `apps/api/**`, `docs/decisions/**`, `docs/handoff/CONTRACTS.md`. Serialize after #232; reconcile additive contract version and renumber colliding ADR0014. Require strict claims-output/v1 validation, cited context ID and quote scope, malformed/uncited/fabricated output fail-closed, verifier determines support/confidence rather than hardcoded1, numeric mismatch authority stays deterministic. Tests missing/unknown citations=>typed abstention+rejection, genuine provider output different from context, numeric contradictions, empty/refusal, mocks/browser goldens and telemetry. Close independently reviewed merged PR full criteria; no secret for offline test transport.

### #194 — tool execution policy — P1, partial

Cancellation/NULL priority fixes shipped (verify integrated tests, do not redo). Paths `workers/src/fel_workers/extraction/**`, `workers/tests/**`, docs runbook; `packages/providers/**` if actual tool contract changes, separately authorized. Decide smallest truthful surface: either bounded runner invokes role allowlist with per-call budget/audit/cancel checks, or explicitly defer tools and remove misleading declarations after parent requirement consistency ruling. Tests unauthorized calls rejected by production execution path; no hidden unbounded loop. Close decision+code+docs, calibration remains #62.

### #195 — live provider layer — P0, implementation + conditional ADR

Main has interfaces/mocks only. Paths `packages/providers/**`, `apps/api/app/retrieval.py`/provider factory, `workers/src/fel_workers/__main__.py`, `workers/tests/**`, API provider tests, `docs/decisions/**` and fixture pins as explicitly authorized. Start smallest approved OpenAI structured+embedding adapter behind frozen interfaces with injected HTTP transport; worker and API pin actual provider/model. Don't build two vendors speculatively; retain/reject #195's two-adapter acceptance explicitly via lead ruling; competitor only for authorized measurement. Tests strict schema, refusal,429/timeouts/retries,usage/cost and redaction, absent secret fail closed, worker starts live without mock flag. #221 before activating live stage. Close working approved provider and reconciled ADR/#132/#62 prose, credentialed smoke via #177/#62. Proposed0012 does not block approved baseline.

### #196 — bounded refactor — P2, implementation

Depends merged #232/#241 and #221 correction before moving atomic code; before #61/#62 large feature edits where practical. Paths `apps/api/**`, `workers/src/fel_workers/extraction/**`, `workers/tests/**`. Extract retrieval routes/pipeline/persistence/idempotency/SSE/serialization and stage bodies keeping FSM/fences/hash authority central. Reuse existing abandoned-branch material selectively after review, no wholesale branch merge. Acceptance existing tests unchanged, golden serialized output/checkpoint hashes byte-identical, no public behavior change, targeted complexity reduction with roughly500-line goal; don't split arbitrary files only for count. Close pure refactor independently from features.

### #197 — M4/M5 persistence design — P1, partial

0009 org FKs shipped. Remaining decision active_scenario_id and absent M4/M5 tables. Paths require expanded registration: subordinate data-model/spec plan under `specs/**`, `docs/decisions/**`, `packages/contracts/**`, `db/migrations/**` + harness; issue's existing worker-test bounds not enough. Draft/accept immutable graph/version/node/edge/scenario/override/forecast/export contracts; composite tenant FKs/RLS, approved-record version provenance, revision/concurrency/cutoff rules. Add active_scenario FK once scenarios exists (or deliberate drop contract decision). Serialize small migrations before #64/#66. Gate unknown-org insert already proved, new cross-tenant immutability/diff/restore/run-pin constraints and migration/restore smoke. Close design AND transferred implementation tracked by explicit owners; don't pretend #63 in-memory engine requires retroactive DB rewrite.

### #200 — reproducible deploy/runtime health — P1, partial

Split requirements and health module shipped; httpx2 already gone. Paths `requirements*.txt`, appropriate lockfile/tool config, `.github/workflows/**`, `infra/railway/**`, `workers/src/fel_workers/health.py`/entrypoint, `workers/tests/**`, first-party pyprojects if dependency metadata corrected. Authorize shared edits. Lock complete application dependency closure including first-party install dependencies with hashes; CI audit actual closure; runtime builds exclude dev tooling. Wire effective worker health route/port and distinguish startup health from continuous watchdog restart (don't assume platform startup probe restarts stalls). Gate two clean builds same dependency versions, no dev imports, live health stale signal + demonstrated configured recovery; correct infra README. Close full original reproducibility/liveness acceptance, not split alone.

### #201 — enforcing retrieval gate — P1, partial

CLI/golden #243 shipped; deterministic mock recall0.4692 truthfully fails threshold. Paths `evals/**`, `.github/workflows/**`, `Makefile`, `packages/retrieval-evals/**` only if runner interfaces need change. Protected CI deterministic regression separate from full credentialed quality gate; missing provider/data must fail closed for release job. Keep canonical0.90 unchanged; follow declared reranker top100 trigger when real frozen gate fails. Tests intentional regression reddens gate, empty support/missing corpus fail, immutable goldens; #132 closes full live gate, #201 closes CI enforcement. Narrow passing subset cannot replace65 release gate.

### #203 — CI and observability residual — P1

Worker optional Sentry init shipped #242; API half in #232. Expand paths `.github/**`, `pyproject.toml`, `vitest.config.ts`, `package.json`/lock and requirement tooling if coverage dependencies, `apps/api/**`, `workers/tests/**` for observability checks. Measure actual Python/JS branch baseline then reviewed ratcheting floors; no invented90% assumption. Required-checks manifest matches current real check names and applied protected-branch settings; second qualified CODEOWNER only if actual staffing available (do not fabricate identity). Browser cache key pinned Playwright+OS architecture, installation deps and cache restore verified. DSN-only optional init/no PII tested; runtime SDK installed when enabled. Gate deliberate coverage regression fails and CI cache works; apply branch rules as explicit lead action. Close all retained checklist or documented scope disposition for staffing/version matrix.

### #219 — AST / iterative scope — P1, decisions first

Paths `specs/001-financial-evidence-lab/spec.md`, canonical ledger only if adding tasks, `packages/calculation-engine/README.md`, `docs/decisions/**`; implementation later `packages/calculation-engine/**`. Decide each clause independently: implement, defer with rationale, or amend. Smallest existing Operator enum may warrant spec amendment for AST; iterative cycles require cap/tolerance/nonconvergence/Decimal precision/bitwise replay/provenance contract if retained. Gate two recorded rulings, consistent parent spec and engine limitations, accepted ADR and tasks for retained work; if implemented, parser safety/property tests and deterministic convergence failures. Close ruling+all chosen deliverables, not leaving promised untracked work.

### #221 — convergent checkpoint repair — P0

Depends #236 shipped, before #195 live activation/#62. Paths `workers/src/fel_workers/extraction/persist.py`, checkpoint/workflow only necessary, `workers/tests/extraction/**`. Reproduce against current row-output architecture with fresh Postgres-backed stores and corrupt output/hash; rerun provider returns different data. Targeted succeeded-unique conflict UPDATE must advance output AND matching hash, response/usage together, preserve identity pins/status, within existing atomic step/events transaction; latest memory state cannot hide broken durable row. Gate second fresh resume does not rerun, budget consumed once for repair, evidence/hash consistency and immutable identity unchanged, deterministic stub also tested if current regression reproduces. Close real DB regression. Event-query fix described by old issue is obsolete.

### #230 — race wait diagnostics — P2

Paths `workers/tests/test_ingestion_pipeline.py` plus worker-test helper if needed. No external deps; serialize workers/tests owners. Add timeout diagnostic naming lock predicate/bound, visible under pytest -q; normal success silent/no extra wait. Force predicate false with short injected bound and prove warning captured, no30sec regression test. Warning-first matches issue requested tradeoff; hard failure only justified measured runner evidence. Close tests proving timeout visibility and normal path unchanged.

### #248 — flaky functional timing — P2

Paths `apps/api/tests/test_retrieval_api.py` (additional opt-in performance harness ownership if needed). Serialize after #232/#241. Replace noisy wall-clock correctness assertion with load-independent query-count/N+1/operation-budget invariant and preserve a separately marked controlled p95 suite for T0215. Do not inflate arbitrary2sec threshold. Gate loaded-host repeated functional test and intentional extra query regression; opt-in performance report uses declared environment. Close stable default CI without losing actual performance owner.

### #249 — Node24 migration — P2, resolved this session

PR #250 merged at `9e59edb`; root confirmed. Allowed `.node-version`, `.nvmrc`, `package.json`, README, local dev doc, workstreams. Acceptance Node24.20.0/engine24, pnpm10.33 frozen lock, format/lint/types/unit/build/browser/CI; hosted Railway verification remains outside task. Record as closed-by-session, do not redispatch. Final audit count should fall38 before any other issue closures.

## Recommended execution order / dependency corrections

1. Finish current review train #232 then #241 with serialized contracts and distinct ADR/version decision; merge corrected #251 docs/spec/plan. #249 already done. Do not close #191/#203 merely from232 if residuals persist.
2. Register narrowed residual owners/paths, terminal tracker treatment, prerequisites. In independent disjoint slices: #230 tests; #248 after API PRs; #190 effective role; #200 runtime closure; #203 CI gates (serialize shared .github/root config ownership). Decision-only #153/#154/#197/#219 can be prepared but contracts/ADRs serialized.
3. Financial-integrity prerequisites #153/#154/#221, tool policy194; behavior-preserving #196 after current correctness PRs before next large feature edits. #61 review+135 mounted stream after API paths freed, without inventing old cleared gate blockers.
4. #195 approved-baseline live adapter after221, #137 provenance. #177 provisions and orchestrates56/81/132; #201 CI gate. Do NOT require completed #62 to choose approved baseline: avoids #177↔#62 cycle. #108 distinct hosted reader follows infra/integrity/preprovision fixes and serialized broad paths.
5. #62 calibration and real all-path approval proof after61 and live prerequisite. Explicitly close M1/M2 gates rather than accepting downstream fixture preparation as prior gate passage.
6. #197 contract slices precede #64 and66; #219 disposition before M4 closure. #64→#65 then66 (UI contention)→#67→#68. #68 also requires65 despite missing historical graph edge, live gates and hosted reader.
7. Closure sweep live GitHub again; each of39 snapshot IDs maps to merge+evidence or explicit disposition. Close leaf acceptance,96→87, milestone4–8, architecture188. Keep scopes/approved deferrals honest; don't mark tasks solely because corresponding issue closed.

## Coverage gaps / decision register

- #197 must own actual M4/M5 schemas/contracts and active_scenario_id disposition, not only already-shipped org FKs.
- #219 closes unallocated AST/iterative clauses; FOR-004 export distinctions explicitly #68.
- T0215 concrete performance owner #132 needed; #137 original checklist has no performance work.
- #108 missing infra web config and integrity UI fix need durable named owner (child issue or lead-owned sequential slice) outside smoke's stop/escalate rule.
- #191 pagination/bounded-reader contract after232; #200 deployment health+full lock/audit after242; #203 root configs and actual branch protection. Each needs corrected allowed paths.
- #195 provider factory wiring requires API/worker paths missing current proposed package; only accepted baseline can proceed without new provider ADR.
- #62 NULL-unscored vs0-insufficient calibration semantics; #194 canonical allowlisted-tool promise vs deletion choice; #153 unit vocabulary/identity version; #154 bound semantics/identity version; #219 formula/iteration scope; #197 lifecycle/tenant persistence; #201 honest non-release mock baseline vs unmodified release quality threshold.
- #177 external actions: budget, identities/secrets, two qualified adjudicators; no credentials presumed provisioned from abandoned-branch comments. Hosting production auth acceptance must be checked under #68, separate from approved #108 mock-auth isolated smoke.

## Live refresh during review

Second GitHub inventory: still39 open, but snapshot changed: #249 closed and #252 newly opened by root for CI audit blockers. The refreshed GitHub query records the current 39. Thus this artifact covers40 distinct session IDs: initial39 plus252.

### #252 — current dependency advisory gate — P0 immediate PR prerequisite

New issue owns mandatory audit failures observed in fresh CI run34425748418 on #232 (six named GHSAs in its issue body). The security remediation agent is implementing minimum patched Next16.3.3/Vitest4.1.11 and transitive floors baseline-browser-mapping2.11.0/js-yaml4.3.2/sharp0.35.4, frozen dependency behavior otherwise. These versions are the issue's requested remediation targets, not independently re-researched by this audit. Paths `package.json`, `apps/web/package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, existing Vitest-constraining manifests; contract-change + owner authorization already recorded. Gate format/lint/typecheck/fullJS tests/web build/audit all pass; regenerate lock deterministically; no suppressions instead of fix. Serialize shared manifests/lock with other PRs, merge onto current integration branch, rerun affected PR checks. Close bounded advisory patch and verified audit before #232/#241 merge; this replaces no milestone work.

## Review-session merge evidence

The audit above is a dated source/issue snapshot. Session integration has since
merged #250 at `9e59edb` (closes #249), #253 at `3dfe678` (closes #252), and
#232 at `eb8b7c8` (retains #191/#203 residuals), and #241 at `5e1faa6`
(closes #193). There were 37 remaining open issues after these merges. Final PR outcomes and remaining
issue count are recorded in `docs/handoff/STATUS.md`. None of these merges
certifies a live milestone gate.
