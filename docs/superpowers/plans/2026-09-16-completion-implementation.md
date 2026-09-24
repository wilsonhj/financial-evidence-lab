# Spec-driven completion implementation and external-agent handoff

Date: September 16, 2026. Specification: [completion specification](../../research/2026-09-16-completion-spec.md). Parent canonical specification/plan, accepted ADRs and sole task ledger govern. This is an execution plan, not a duplicate completion ledger. It introduces no claim of live acceptance. Baseline inspected: main `2551454`; resolve current heads before work.

## Execution contract

The owner authorized implementation, public signup/private workspaces, user-funded BYOK with OpenRouter first/direct providers later, driver overrides, historical-error intervals and a deterministic derived-fact bridge. Formal contract freezes remain prerequisites for new APIs/storage, provider substitution and proposed numerical/method choices. Root integration lead owns registration, shared-path ADR/contracts/migrations, GitHub coordination and merge decisions; these documents do not silently expand any current allowlist.

Use 50 named roles in stages, **at most three writing implementers plus lead concurrently**. Roles are staffing slots, not a promise of 50 simultaneous processes. Read-only reviewers consume the same four total active slots (including lead); schedule them in place of writers, never in addition to four active agents. No agent edits another owner's files. Shared seams have one lead-designated writer. An external agent receives exactly one registered child issue, branch/worktree, immutable base/contract SHA, explicit file allowlist and acceptance criteria. Parent issues retain integrated acceptance and canonical ownership. Register split children before implementation; dependencies and path-glob containment are checked before every dispatch.

Contracts, migrations, generated types, root configurations and registry edits serialize through lead. Allocate migration numbers at dispatch, never in advance across branches. Exact retries, hidden-tenant errors, bounded input/list contracts and generated client types follow existing conventions. Open draft PRs early, push resumable checkpoints, record exact head/tests/evidence/blockers/next action. Independent review must target the final head. A verified defect gets a failing reproduction before minimal repair; do not turn a broad review into speculative refactoring.

## Waves and dependency gates

1. **Control and immediate evidence:** register children and shared-contract rulings. PR #320 was reviewed at exact rebased head `e9ddc0bfe1450fc5de40987bf0fbe3f1b656e14f`, passed required checks and merged at `69ed8b9`; retain that evidence without claiming hosted proof or redispatching the completed repair. Audit #61 reference target, #108 hosted target, #292 identity, #191/#203 runtime evidence and current open PRs. Finish actionable local preparation; external-resource absence stays an explicit blocker.
2. **Identity, provider and data foundation:** freeze public signup/BYOK contract, credential ownership/encryption/revocation/job binding, OpenRouter adapter capabilities and metering. Implement disjoint auth, vault, provider and UI slices. Run no billable calls without approved user-owned credentials/budget. Prepare corpus/SEC/benchmark work in separate dataset subtrees; live cutover #177 and #132/#201 evidence depend on adapter and resource readiness.
3. **Confidence:** fixture-only dataset/calibrator preparation may proceed only through registered preparatory children. Final #62 integration waits for #61 and #177 acceptance. Freeze owner policy API and calibration rules, prove no-auto-approval across all paths, and publish live extraction release evidence.
4. **Models:** #64 waits for #62 and existing engine prerequisite. Freeze graph/scenario/derived-provenance contract and additive storage migration. Codec, source adapter and store may then run disjointly; scenarios/HTTP integrate afterward. Complete #64 acceptance before #65/#66 runtime dispatch. Preregister three benchmark runs; every run passes.
5. **UI and forecasting:** split model graph/analytics/history ownership from Forecast Lab UI. Freeze forecast storage/API/jobs/methodology, then baseline/driver/statistical/ensemble algorithms and runtime. #67 backtests/intervals follow accepted #66. Forecast UI always shows baseline and explicit unavailable/abstained states.
6. **Audit/export/release:** benchmark drafting and contract design may prepare through registered children; final #68 runtime/release waits for #67 and all inherited gates. Freeze export storage/API, implement lineage and disjoint renderers/publication, then complete end-to-end, hosted, security, load, restore and signed release acceptance. Only lead reconciles canonical tasks and parent issues.

No downstream milestone bypasses its predecessor exit gate. Design/fixture preparation is explicitly separate from feature dispatch or completion. Existing broad parent allowlists are narrowed in the registry before parallel child writers begin.

## Fifty-role handoff roster

Paths below are proposed bounded ownership, finalized verbatim or narrowed by the lead's dispatch manifest. New modules are not permission to alter nearby facades/conftests. Tests live beside their owned feature or in the named focused subtree. Common `main.py`, consumer entrypoints, OpenAPI, generated types and shared fixtures belong exclusively to the contract/integration writer during a scheduled window.

| Role | Deliverable and owner boundary | Prerequisite and acceptance |
|---|---|---|
| 01 Lead | Registry, ADRs, shared integration seams, issue/PR and release decisions | Validate DAG/nonoverlap; freeze contracts; only lead closes criteria |
| 02 Contract engineer | Named shared schemas/OpenAPI/migrations/generated outputs, serialized per wave | Exact request/response/job/errors/roles/limits and PostgreSQL harness; no concurrent shared writer |
| 03 Signup/auth | New bounded signup/bootstrap API modules and focused tests | Frozen contract; atomic private organization/workspace bootstrap, membership/role denial, hosted identity #292 |
| 04 Credential vault | New BYOK storage/service modules and focused tests | Frozen key management; user-owned encrypted secrets, validation/rotation/revocation, no disclosure/fallback |
| 05 OpenRouter adapter | Named `packages/providers/` adapter module/tests | Accepted provider ADR/capability contract; structured output/errors/timeouts/cost provenance and pinned routes |
| 06 Direct adapters | Separate provider adapter modules/tests | After common BYOK interface; no silent fallback or unsupported embeddings inference |
| 07 Usage/budgets | Named metering and credential/job binding modules/tests | Atomic hard-limit enforcement/revocation checks; live accounting #191; no payer substitution |
| 08 Auth/BYOK UI | New auth/settings feature subtree and tests | API frozen; metadata-only secret state, accessible actionable failures, private defaults |
| 09 Load acceptance | Existing #61 benchmark allowlist | Dedicated documented target, frozen scaled-fixture25-user protocol/raw samples; separate full-reference release proof; all thresholds unchanged |
| 10 Hosted reader | Existing #108 named harness/browser/report allowlist | Dedicated target; ingest→reader, competing versions, actual outage, recovery/sanitization |
| 11 SEC recovery | `evals/datasets/sec-fixtures/**` | Approved identifying contact/fresh fetched bytes; ≥8 stress features, preserve cohort |
| 12 Corpus publication | Named live-ingestion harness/report subtree | #177 credentials/adapter;20 issuers, hashes/cutoffs/idempotency/quality artifact; #56 relationship |
| 13 Retrieval evaluation | Named live65 harness/report subtree | Frozen corpus/providers; #132/#201 Recall@10 and complete live benchmark gates |
| 14 Calibration labels | `evals/datasets/extraction-calibration/**` and focused validator tests | Approved non-tenant adjudication; issuer/time disjoint splits, immutable hashes |
| 15 Calibrator | `workers/src/fel_workers/extraction/calibration/**`, focused tests | Frozen100/20-per-outcome rules; deterministic PAV/breakpoints/metrics/fail-closed behavior |
| 16 Policy API | New extraction policy API module/tests | Owner-only immutable/audited .85/.80 defaults, [0,1], concurrency/idempotency/tenancy |
| 17 Calibration integration | Exact registered extraction validation/persistence seams | #61/#177; historicNULL preserved, new insufficient0/high; every path human approval |
| 18 Extraction gates | Named extraction eval harness/tests/reports | Exact guidance/KPI/numeric/temporal gates, M2 contradiction link, live provider failures/smoke |
| 19 Snapshot codec | `snapshot_codec.py` and its focused engine tests | Exact v1/v2 canonical roundtrip/hash/ancestry; strict bounded decoder, no hash rewrite |
| 20 Model store | New modeling store module/focused DB tests | Frozen graph migration; atomic projections, corrupt-load rejection, scopes/immutability |
| 21 Source binding | New modeling sources module/focused tests | Approved reported scalar pins, exact scale/calendar/unit mapping, complete evidence, typed rejection |
| 22 Derived bridge | New engine derived-source module/focused tests | Separately frozen provenance; Q4 bridge only compatible fiscal/unit/accounting/vintage inputs |
| 23 Scenarios | New modeling scenario module/focused tests | Complete sparse replacement; forward-period drivers/assumptions only; reject historical overrides, unchanged reported history, branching/restore-as-child |
| 24 Model HTTP | New modeling route/request modules/HTTP tests | Store/sources/scenarios; generated contract, receipts/ETags, bounded history, rollback |
| 25 Graph UI | `apps/web/src/features/modeling/graph/**` | #64; keyboard/table graph, source/formula/driver inspection, reduced motion |
| 26 Analytics UI | `apps/web/src/features/modeling/analytics/**` | Frozen view models; bridges/waterfalls/treemap/heatmap/tornado/scenario charts, accessible alternatives |
| 27 Model history UI | `apps/web/src/features/modeling/history/**` | Exact versions/diff/restore/citations, explicit activation, preserve stale drafts |
| 28 Forecast storage/API | New forecast API/store modules and tests | Frozen forecast migration/jobs; immutable requests/results/points, atomic outcomes/idempotency |
| 29 Baselines | Forecast `baselines.py` and focused tests | Fiscal last-value/seasonal-naive,1–8quarters, explicit short-history behavior |
| 30 Driver forecasts | Forecast `drivers.py` and focused tests | Exact model/scenario/assumption pins; revenue/ARR-disclosed/gross-profit Decimal outputs |
| 31 Statistical challenger | Forecast `statistical.py` and focused tests | Frozen additive damped-trend seasonal ETS; <12quarters abstains; reproducible config/version |
| 32 Approved ensemble | Forecast `ensemble.py` and focused tests | Frozen equal-weight eligible members; no hidden promotion or absent-member substitution |
| 33 Forecast runtime | Forecast orchestration modules/worker tests | Provider/feature/budget checks, leases/retries, no partial-success publication |
| 34 Forecast Lab UI | `apps/web/src/features/forecasting/**` | Baseline comparison, contributions/error/interval/method/cutoff, explicit abstention; no analogues |
| 35 Rolling backtests | Forecast `backtest/**` and focused tests | Actual publication vintages per origin, no corrected-data leakage, horizon split |
| 36 Interval calibration | Forecast `intervals/**` and focused tests | Same issuer/target/horizon≥19 residuals, finite conformal ranks50/80/95, no implicit pooling |
| 37 Forecast gate | Named forecast evaluation harness/tests/reports | Seasonal-naive median-MAE default gate,80%coverage75–85%, immutable method/data provenance |
| 38 Audit/export | Split sequential renderer/publication children under `packages/export/**` and named API modules | Full typed lineage, MD/PDF/CSV/XLSX/JSON/manifest; verify bytes before immutable publication |
| 39 Frozen benchmark/release | `evals/datasets/release-300/**`, named release harness, `docs/release/**` | Two qualified human adjudicators,≥300/≥20issuers/≥30category; signed all-gates artifact |
| 40 Spec reviewer | Read-only requirement/issue/contract traceability report | Detect omitted parent requirements, duplicated ledgers, false completion |
| 41 Security reviewer | Read-only auth/secret/SSRF/injection findings with repro | Cross-user/tenant keys, revocation, log/export leakage, owner-fallback prohibition |
| 42 Database reviewer | Read-only migrations/RLS/concurrency review | Empty/representative migration, restrictive references, immutable rows, rollback |
| 43 Provider reviewer | Read-only adapter/error/budget evidence | Capability pinning, real usage, unknown model rejection, no undisclosed substitutions |
| 44 Financial reviewer | Read-only decimal/unit/calendar/provenance report | Scale once, bridge compatibility, reported/derived distinction, unchanged historical facts |
| 45 Statistical reviewer | Read-only calibration/backtest/method report | Independent splits, ranks/support counts, temporal leakage, defaults justified by evidence |
| 46 Accessibility reviewer | Read-only browser/a11y report | WCAG2.2AA, graph/table keyboard flows, reduced motion, chart alternatives |
| 47 Performance reviewer | Independent preregistered benchmark verification | Three model runs all pass, frozen load protocol, no best-run or undersized-target claim |
| 48 End-to-end reviewer | Read-only deployed workflow evidence | Signup→BYOK→ingest→review→model→forecast→export, failure/recovery/private boundaries |
| 49 Release/restore reviewer | Read-only backup/restore/artifact audit | Real restore, required gates, all hash/provenance signatures, hosted telemetry/CODEOWNER |
| 50 Independent PR reviewer | Exact-head review with verified reproductions | Findings returned to owner; no shared-file edits or self-approval |

Roles38/39 split into additional child issues sequentially as required, without increasing the fifty-role staffing budget. Human adjudicators and resource owners are external dependencies, not simulated agent roles. Review roles never apply competing fixes; package owners repair confirmed findings.

## Frozen choices, testing and completion

The execution proposal selects calibration≥100 labels/≥20 of each outcome per stratum, issuer/time-disjoint splits; ETS additive damped-trend seasonal challenger with12-quarter minimum; equal-weight approved ensemble; finite conformal residual intervals with19 same-issuer/target/horizon samples and no implicit pooling. These require formal contract freeze and independent validation before dispatch. They are not evidence that accuracy or coverage gates pass. Model import/provenance, derived bridge, sparse overrides and no-owner-key fallback follow the completion specification.

Each dispatch manifest records: parent/child issue; base+contract SHA; sole owner/branch; exact allowed/forbidden paths; prerequisites; failing regression or new acceptance test; targeted commands; immutable evidence location; rollback/cleanup; credential capability names only; reviewer; return conditions. An agent encountering a missing API/schema/shared helper stops that dependent edit and requests the lead's bounded contract change, while continuing independent owned tests.

Required evidence includes real PostgreSQL where durable state matters, exact-head required CI, integrated HTTP/worker/browser workflow, tenant and same-tenant cross-workspace rejection, concurrent ETag/idempotency, secret sanitization, cancellation/revocation/retry, unavailable-provider and insufficient-data states, temporal/hash tampering, accessible UI and reference performance. The #61 scaled-fixture 25-user acceptance and parent full reference-corpus release load are distinct proofs; retain separate target/workload manifests and never substitute one for the other. Do not add implementation-mirroring tests as acceptance substitutes.

Release aggregate: temporal100%, numeric≥99%, citation entailment≥95%, completeness≥92%, Recall@10≥90%, guidanceF1≥90%, KPI/driverF1≥88%, contradiction recall≥90%, abstention precision≥95%,80%forecast coverage75–85%; advanced default beats seasonal-naive medianMAE1–4quarters. Existing resource/time/cost/load thresholds stay unchanged. Final lead audit resolves every remaining issue criterion, preserves explicit unmet gates, reconciles the sole canonical task ledger, and signs/promotes only immutable artifacts passing the full suite.
