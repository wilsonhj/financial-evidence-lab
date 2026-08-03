# Implementation status

Last updated: 2026-07-30

## Repository

- Default and implementation base: `main`.
- Current `origin/main` tip: `61058e4` (PR #145, M3-EXTRACTION-CORE). Prior notable tips: PR #150 corpus-QA renderer proposal @ `21750b1`, PR #147 ADR-0008 Amendment 1 @ `355d2b6`, PR #144 postcss/brace-expansion remediation @ `eed2140`, PR #127 DB-GUARD-HARDENING @ `e55eea8`. Always resolve trunk against `origin/main`.
- The earlier warning about local `main` sitting at `89e4363` is retired: that commit was reverted on-branch by `7f11bab` before #145 merged, so no `.specify/**` or `AGENTS.md` change landed. Verified by hash — both files are byte-identical either side of `61058e4`.
- Next dispatch: M3-REVIEW (#61) is unblocked now that #60 has merged, and is not yet flipped to `ready`. M3-CONFIDENCE-GATE (#62) is **not** unblocked — it `depends_on: [M3-REVIEW]`, so it waits on #61 merging, not on #60.
- ADR-0009 (`docs/decisions/ADR-0009-checkpoint-payload-in-event-stream.md`, Status: **Proposed**) landed with #145 under shared `docs/decisions/**`. It covers whether `stage_output` should carry evidence text verbatim, which is adjacent to the open M4 ruling below.
- Canonical product spec: `specs/001-financial-evidence-lab/spec.md` v1.2.
- M2 implementation design: `specs/002-observable-hybrid-retrieval/` plus ADR-0006 (live on main).
- M3 implementation design: `specs/003-agentic-extraction/` plus ADR-0007 (live on main).

## Completed

- M0 platform/contracts/CI foundations.
- M1 ingestion, evidence UI, corpus QA, companyfacts follow-up, and worker deployment.
- Reader contract/global offsets plus production API and HTTP web runtime:
  - PR #92 / issue #89 — contract
  - PR #91 / issue #90 — global offsets
  - PR #98 / issue #94 — reader API
  - PR #99 / issue #95 — HTTP reader runtime
- READER-CROSS-STACK mock-first + CI stack path: PR #105 / package issue #96 (criteria 1–10).
- M2-CONTRACT OpenAPI v0.3.0 + migration `0003_retrieval_core.sql` + pgvector CI image: PR #106 / issue #100 (closed).
- M3-CONTRACT OpenAPI v0.4.0 + migration `0004_extraction_core.sql` + `StructuredLLMProvider` mocks: PR #112 / issue #101 (closed); review fixes included typed records, conflict identity pin, terminal-run proposal freeze, step success-demotion guard.
- M2-RETRIEVAL-BACKEND full package: PRs #114 + #119 / issue #57 (closed) — item builder, versioned index publish + exact-vs-HNSW oracle, cutoff-safe lanes, deterministic planner, RRF k=60 fusion, query/trace/SSE/rerun/feedback API with persisted byte-stable replay; acceptance report at `packages/retrieval/ACCEPTANCE.md`.
- M2-CLAIMS-VERIFICATION full package: PR #122 / issue #58 (merged) — atomic claim decomposition, citation entailment/verification, abstention, 50–100-question smoke gate, retrieval/performance suite; live 65-question exit gate deferred to follow-up #132.
- M2-OBSERVATORY-UI full package: PR #123 / issue #59 (merged) — Search Observatory trace timeline, lane toggles, evidence feedback, and replay; browser E2E and live SSE deferred to follow-ups #131/#134/#135.
- Dependency-advisory remediation chain on `main`: PRs #128 (js-yaml GHSA-52cp @ `ad1717b`), #140 (fast-uri/sharp + fail-closed audit-gate triage @ `ef13b0f`), #142 (globalize postcss override @ `1208028`), #144 (postcss floor `^8.5.23` + brace-expansion GHSA-mh99-v99m-4gvg @ `eed2140`). All four touch `shared_paths` and are the class of change #141 is about. The `brace-expansion` entry in `scripts/audit-allowlist.json` is **package-wide and expires 2026-10-24** — it will mask any future finding for that advisory, including against a 5.x resolution. Scheduled refresh tracked by #143.
- DB-GUARD-HARDENING: PR #127 / issue #125 (closed) — retroactive 0005 authorization record, as-fel_app guard-harness pass, superseded-pin regression, helper consolidation.
- Migration `0005` query-guard role fix (fel_guard_query FOR SHARE vs SELECT-only fel_app): PR #118, with as-fel_app harness regression.
- Retrieval integration suites isolated in a dedicated `<db>_retrieval` test database (cross-suite FK isolation defect found by first CI exposure): PR #119.
- CI migration-harness gate (`db/migrations/tests/*.test.sql` run in the database job): PR #115; database job now logs `OK: 3 migration harness(es) run` (0003 + 0004 + 0005 from #118).
- External benchmark and ontology research recovered from PRs #74/#75 onto the M2/M3 design branch without merging retired `integration/m0` history.
- Issues #57–#62 refreshed to current `main`, concrete dependencies, bounded paths, and implementation acceptance gates.
- Contract-change issues #100 (M2 v0.3.0) and #101 (M3 v0.4.0) created with serialized shared-path ownership.
- M2/M3 implementation design PR #102 merged to main @ `052836d` (Spec Kit packages, ADR-0006/0007, research reconciliation, contract gates documented).

### Merged since 2026-07-21

- Dependency and CI-hygiene remediation: PR #140 (fast-uri/sharp advisories + fail-closed audit-gate triage), PR #142 (postcss override globalized for GHSA-r28c-9q8g-f849), PR #144 (postcss floor `^8.5.23` + brace-expansion GHSA-mh99-v99m-4gvg). Note `eca02df`: the first brace-expansion `^5.0.8` override was reverted before the scoped remediation landed — do not reinstate it without re-reading #144. Recurrence prevention is tracked on #143 (scheduled advisory refresh), still open.
- Research recovered to trunk: PR #117 — FinRobot cherry-pick studies (M4 calc-engine port, M3 extraction-role pattern).
- ADR-0008 Amendment 1: PR #147 @ `355d2b6` — adds `infra/railway/worker.json` to the scaffold-registration exception, install-list append only. Ratified in the carrying commit with date, actor and PR number, matching the ADR-0005/0006 convention; supersedes the earlier "Proposed, ratified on merge" wording that had reopened finding I2.
- Corpus-QA report renderer proposal: PR #150 @ `21750b1` — `docs/research/evals-report-renderer-proposal.md`. Proposal only; authorizes no code change. Registered below as `EVALS-REPORT-RENDER`; size-lever decision recorded there.
- **M3-EXTRACTION-CORE full package: PR #145 @ `61058e4` (2026-07-30) — issue #60, 115 files, +15,326.** SaaS ontology package, five typed extraction roles, durable workflow FSM with checkpoint/resume over the event log, normalization, deterministic validators, atomic persistence, hard budgets, and audit redaction. Ships `packages/ontology/**` (a new first-party package), `workers/src/fel_workers/extraction/**`, `docs/runbooks/extraction-worker.md` and `workers/src/fel_workers/extraction/OPERATOR.md`.
  - Scope delivered: `packages/ontology` saas-metrics/v1 (14 metrics / 9 families), bounded durable extraction workflow (budgets, checkpoints, five typed roles), Decimal normalize/validate, `extraction_run` consumer dispatch, proposals always `needs_review`. Earlier on-branch remediation: numeric parser truncation (`4200000` → `420`), evidence truncated to 64 chars on resume, mock model bound unconditionally in the production entrypoint, worker packaging, budget reset per retry, runs stuck `running` after untyped escapes. Two defects found by first real-Postgres coverage: four of five terminal paths never wrote their terminal event (0004 rejects child inserts once a run row is terminal), and content-triggered mock controls (`ABSTAIN`/`REFUSE`) were reachable from untrusted filing text. Live OpenAI deferred to #62; terminal-run retry semantics to #146.
  - Merged after four review rounds. Final round fixed one blocker and three majors that the suite did not catch: the gross-profit identity inverted for contra-presented COGS, a normalizer-rejected row disabling identity checks for clean siblings, `wall_seconds_used` read latest-not-greatest, and the same polarity defect unfixed in `_check_rpo_balance`. M4 (redaction inside `stage_output`) was investigated and assessed a **false positive** — the frozen schemas intersect `_REDACT_KEYS` at exactly `{"text"}`, already exempted — and is still awaiting a formal ruling.
  - Deliberately deferred out of the PR: **#153** (unify unit-case handling across identity, duplicate and definition checks — a one-sided fold was tried and reverted because it made a real break invisible) and **#154** (guidance range ordering: polarity-blind `check_range`, plus no ordering check at all for free-text `metric_id`s). Both move persisted identity keys and need an ADR.
  - Verified at merge: 1047 passed, 0 skipped against Postgres 17 + pgvector with `TEST_DATABASE_URL` set; five CI jobs green.

### Tracker note — #96 residual owned by #108

Issue #96 remains **open** as a tracker only. Package `READER-CROSS-STACK` is `merged` via #105 for its `evals/**` mock/stack scope. Remaining acceptance **criterion #11** (production worker → Postgres → FastAPI → real `HttpEvidenceSource` → production Next.js reader + browser/hosted artifacts) is owned by **READER-PROD-SMOKE (#108)**. Do not re-dispatch #96; do not treat #96-open as blocking #57.

## Design gate (closed)

PR #102 merged to `main` @ `052836d`. Design gate is closed. Spec Kit packages, ADR-0006/0007, and recovered research are on trunk.

Still research-draft (not a dispatch blocker): recovered benchmark needs SEC timestamp/provenance/negative-case/range gates in the M2 compiler; recovered ontology needs citation/provenance fixes or explicit v1 exclusion.

## Active

1. **In review:** DOCS-ONBOARDING (#148) — branch `agent/developer-docs`, PR **#149** open at `11145c5`, all five checks green, `mergeStateStatus: CLEAN`. Paths `README.md`, `docs/architecture/**`, `docs/development/**`. Nothing else may claim its paths until this merges.

   Refreshed against `61058e4` on 2026-07-30, which cleared what was previously recorded against it here: the six assertions that the M3 runtime was unmerged (including `system-design.md`'s "downstream code must not assume that PR's runtime is available on `main`"), four developer commands that could not run as written, `packages/ontology` missing from both the repository map and the static-check lists, the unreferenced `docs/runbooks/`, and the `eed2140` test-count baseline. Re-verified on-branch at `11145c5`.

## Ready

1. **EVALS-REPORT-RENDER (#151)** — `evals/reporting/**`, `evals/tests/**`; stdlib-only corpus-QA Markdown + SVG renderer per `docs/research/evals-report-renderer-proposal.md` (PR #150). Dependency M1-CORPUS-QA is `merged`; dispatchable now.

Serialization notes: blocked #108 claims `apps/api/**` + `apps/web/**` + `evals/**` + `workers/**` + `.github/**` — if #108 unblocks, do not run it concurrently with any package holding those paths. EVALS-REPORT-RENDER's `evals/reporting/**` and `evals/tests/**` are **subtrees of** the `evals/**` claimed by #108, #62, #67 and #68, so they do overlap; all four are blocked today, so there is no live contention, but serialize against whichever unblocks first. DOCS-ONBOARDING overlaps nothing.

## Blocked (registered, not dispatchable)

1. **Blocked:** READER-PROD-SMOKE (#108) — branch `test/reader-prod-smoke`; child F of #87.
   - Blocker A: hosted deployment credentials not provisioned (request by name only; never claim ready).
   - Blocker B: known product residual — API `INTEGRITY_ERROR` classified as web `unavailable` (no integrity-alert UI kind); #108 must stop-and-escalate, not silently patch.
   - Flip to `ready` only after integration-lead provisions hosted secrets **and** clears the integrity residual (fix landed or explicit lead waiver).
   - Shared `.github/**` gated workflow requires separate integration-lead authorization before any smoke PR edits CI.

## Next (after ready merges)

1. **M3-REVIEW (#61)** is unblocked now that #60 is merged — it was the only package waiting directly on it. Branch `agent/m3-review` (not yet created; paths `apps/web/**`, `apps/api/**`). It carries an **explicit** `status: blocked` in `workstreams.yaml`; flip that one key to `ready` when dispatching.
2. **M3-CONFIDENCE-GATE (#62) is not yet unblocked.** `workstreams.yaml` gives it `depends_on: [M3-REVIEW]`, and `docs/handoff/README.md:26-28` makes a package ready only when *every* `depends_on` package is `merged` — so #62 waits on #61 landing, not on #60. It has **no** `status` key and inherits `defaults.status: blocked`, so dispatching it means adding a key rather than flipping one. #62 owns the live OpenAI adapter #60 deferred; note its `allowed_paths` do not currently include `packages/providers/**`, where the provider protocol lives.
3. **Merge PR #149** (DOCS-ONBOARDING) once reviewed. The refresh against `61058e4` is complete — see Active.
4. **Rule on M4** (redaction inside `stage_output`). Investigation says false positive with evidence; either close it as not-a-defect or change `events.py`'s docstring and the three tests that currently encode the behaviour as intentional. Leaving the contradiction on trunk invites the next agent to "fix" the wrong side. ADR-0009 (Proposed) covers the adjacent question and should be ruled on with it.
5. EVALS-REPORT-RENDER (#151) — dispatchable now; no live contention, but its paths are `evals/**` subtrees, so serialize against #108/#62/#67/#68 if any unblocks.
6. **#153 and #154** — both deferred out of #145, both move persisted identity keys, both need an ADR before implementation.
7. READER-PROD-SMOKE (#108) remains blocked until credentials + the integrity residual are cleared.

### Decision record — EVALS-REPORT-RENDER size lever (2026-07-29)

The proposal offers a lever: drop the committed golden SVG (−110 lines) and prove SVG determinism with a render-twice byte-equality assertion plus structural assertions instead.

**Decision: leave the lever. Commit both goldens.**

Rationale: render-twice equality proves the renderer is deterministic *within one process*, which is strictly weaker than a committed golden. Only the committed artifact catches cross-version serialization drift — precisely the risk the proposal itself flags when it verifies that `ET.tostring` preserves attribute insertion order on Python 3.11. A future interpreter upgrade that reorders attributes would pass render-twice and fail golden comparison, and that is the regression worth catching in an evidence product. The `docs/handoff/README.md:35` figure is a stated preference ("prefer PRs below roughly 600 changed lines"), not a gate; of the ~640 changed lines about 150 are golden fixtures rather than review-bearing code, leaving hand-written code near 490.

Accordingly AC8 keeps both goldens and the allowed-paths list keeps the SVG.

### M2 follow-ups (issues opened 2026-07-21)

Tracked after the #122/#123 merges; none blocks #60.

- **#132** — M2-CLAIMS live 65-question exit gate (closes M2-024).
- **#133** — M2-CLAIMS: break numeric identity tautology in unit tests (no external deps).
- **#134** — M2-OBSERVATORY: run Playwright E2E in CI (closes criterion 6 browser-E2E).
- **#135** — M2-OBSERVATORY / M3: mount live same-origin SSE proxy + UI consumer (M3-deferred).
- **#136** — M2-OBSERVATORY: full WCAG 2.2 AA + keyboard-operation audit.
- **#137** — M2-CLAIMS fast-follow hardening (mock→live cutover hygiene).
- **#138** — M2-OBSERVATORY: dedicated web-layer client telemetry.
- PR **#131** — Observatory Playwright E2E in fixture mode (**merged** @ `bc6a2a3`; #59 criterion 6). Re-scope or close **#134** against it: that issue still reads as if E2E-in-CI were outstanding.

### Open issues carried but not queued

These are OPEN on GitHub and own no package entry in `workstreams.yaml`. Listed so resume rule 2 has something to reconcile against.

- **#81** — [EXT-2b] supplemental SEC stress cohort: restore the ≥8 distinct stress-feature bar. Open since 2026-07-13, `agent-task`, appears in neither handoff file.
- **#56** — [M1-CORPUS-QA] open; corpus QA is listed under Completed above, with the T0112 live-artifact residual tracked only as a trailing comment in `workstreams.yaml`. Needs the same explicit tracker note #96 has, or closing.
- **#87** — [M1-READER-INTEGRATION] open, `contract-change`; referenced only as "child F of #87". Neither file states the parent is still open.

### M3 / process follow-ups (opened 2026-07-24 → 2026-07-28)

- **#141** — process: shared-path config changes need `contract-change` label + authorization record. Decision pending.
- **#143** — CI hygiene: scheduled dependency-advisory refresh so CI breakage stops being the discovery mechanism. Note the `brace-expansion` allowlist entry in `scripts/audit-allowlist.json` is package-wide and expires **2026-10-24**.
- **#146** — M3: job retries can outlive a run's terminal state. Reachable via two paths: an untyped escape now lands the run `failed` (terminal), so the queue retries a job that can never resume; and `0004` forbids both deleting runs and mutating terminal ones. Decision pending; whichever option is chosen should also stop the consumer retrying a job whose run row is terminal.

### Test-isolation rule (learned from PR #145, first CI exposure)

CI provisions a fresh database per **run**, but every suite shares it **within** that run. Durable `extraction_runs` rows are permanent (`extraction_runs cannot be deleted`, `extraction_proposal_evidence is append-only`) and pin their `corpus_versions` row, while the shared `corpus_conn` fixture deletes `corpus_versions` globally — so a DB-backed extraction suite on the base URL fails every later suite at fixture setup. Extraction integration tests run against an isolated `<db>_extraction` sibling (`ensure_extraction_database`), mirroring `<db>_retrieval` from #119. Apply the same pattern to any new DB-backed suite in #61/#62.

## Credentials

CI and package implementation remain mock-first for #57/#101. Hosted reader production smoke (#108) requires separately authorized deployment credentials — **not provisioned**; request by name only. Do not treat #108 as credential-ready. Request `FEL_OPENAI_API_KEY` only for the explicitly credentialed live retrieval/extraction smoke gates after deterministic fixtures and contracts pass. SEC source re-verification requires the configured compliant SEC identity and rate limiter; do not commit or log personal contact data.

## Resume rules

1. Treat GitHub merged commits, issues, and PRs as authoritative.
2. Reconcile this file with `workstreams.yaml` before dispatch.
3. Never run two packages that own `packages/contracts/**` / `db/migrations/**` concurrently (#101 vs any future contract owner).
4. Do not dispatch any package whose allowed paths overlap an active package.
5. Keep total active packages at four or fewer.
6. `#96` open ≠ package unfinished; residual criterion #11 is #108-owned.
7. Require tests, telemetry where applicable, documentation, acceptance evidence, and an independent PR review before merge.
