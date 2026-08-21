# Implementation status

Last updated: 2026-08-20

## Repository

- Default and implementation base: `main`.
- Current `origin/main` tip: `5b4b77c` (PR #162, wires the orphaned M3 normalize modules in and deletes the dead duplicate; issue #155). Prior notable tips: PR #164 EVALS-REPORT-RENDER @ `a23514e`, PR #170 memory-stores contract test @ `5f4d9b9`, PR #168 handoff Current-state reconcile @ `64eb571`, PR #166 **Apache-2.0 relicense** @ `5394c64`, PR #167 js-yaml/nanoid advisory remediation @ `7eba341`, PR #165 ADR-0010 (Proposed) @ `ace7b83`, PR #163 measured test counts @ `d44bb06`, PR #152 handoff reconcile @ `a25bf7c`, PR #160 durable job-error sanitization @ `5ec4c08`, PR #149 developer onboarding + architecture guides @ `52c787a`, PR #156 M3 post-merge follow-up @ `263bff8`, PR #145 M3-EXTRACTION-CORE @ `61058e4`, PR #150 corpus-QA renderer proposal @ `21750b1`, PR #147 ADR-0008 Amendment 1 @ `355d2b6`, PR #144 postcss/brace-expansion remediation @ `eed2140`, PR #127 DB-GUARD-HARDENING @ `e55eea8`. The full nine-commit sequence from `5ec4c08` to `5b4b77c` is enumerated under **Merged since 2026-08-04**. Always resolve trunk against `origin/main`.
- The earlier warning about local `main` sitting at `89e4363` is retired: that commit was reverted on-branch by `7f11bab` before #145 merged, so no `.specify/**` or `AGENTS.md` change landed. Verified by hash — both are byte-identical either side of `61058e4`. Re-landing it requires its own `contract-change` PR (#141).
- **`agent/m3-extraction-core` is merged and closed.** #145 was squashed, so its branch tip `04da0fb` is **not** an ancestor of `main`. Do not push follow-up work to that branch — a merged PR cannot track it. M3 follow-ups branch from `main`.
- Next dispatch: **two packages now have every `depends_on` satisfied, and neither is flipped.** **M4-MODEL-CALC (#63)** `depends_on: [M3-EXTRACTION-CORE]`, which merged at `61058e4`; its `allowed_paths` are `packages/calculation-engine/**` alone, which overlap **no** other package's paths and nothing active, so it carries no contention gate. It has no `status` key and inherits `defaults.status: blocked`, so dispatching it means **adding** a key, not flipping one. **M3-REVIEW (#61)** likewise has its dependency satisfied, so its **explicit** `status: blocked` is no longer a statement about dependencies; it is held by two unresolved rulings — #146 (terminal-run retry semantics) and the mutually exclusive ADR-0009-vs-#157 fork. Both flips are the integration lead's call and are deliberately **not** made by this reconciliation. M3-CONFIDENCE-GATE (#62) is **not** unblocked — it `depends_on: [M3-REVIEW]`, so it waits on #61 merging, not on #60.
- ADR-0009 (`docs/decisions/ADR-0009-checkpoint-payload-in-event-stream.md`) landed with #145 under shared `docs/decisions/**` and remains **Status: Proposed**. PR #156 corrected four factually false statements in it, but did **not** ratify it. Its Decision — amend the six published documents down to a weaker guarantee — is **mutually exclusive with issue #157**, which instead adds the `steps.output` column so those documents stay true. That fork needs an integration-lead ruling before either lands.
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
- Dependency-advisory remediation chain on `main`: PRs #128 (js-yaml GHSA-52cp @ `ad1717b`), #140 (fast-uri/sharp + fail-closed audit-gate triage @ `ef13b0f`), #142 (globalize postcss override @ `1208028`), #144 (postcss floor `^8.5.23` + brace-expansion GHSA-mh99-v99m-4gvg @ `eed2140`). All four touch `shared_paths` and are the class of change #141 is about. The `brace-expansion` entry in `scripts/audit-allowlist.json` **was** package-wide with a 2026-10-24 review date; it was removed by #156 and the file is now `[]`. Scheduled refresh tracked by #143. **PR #156 @ `263bff8` extends the chain:** two incomplete-fix follow-ups (`GHSA-rgw5-rvv9-x895` brace-expansion, `GHSA-7p8r-x3mc-p8w7` fast-uri) moved the floors again, so they went to `^5.0.9` / `^2.1.4` / `^3.1.5`. Because `brace-expansion@2.1.4` now exists on the 2.x maintenance line and `minimatch@5.1.9` declares `^2.0.1`, the previously unfixable remnant is patched rather than suppressed — `scripts/audit-allowlist.json` is now `[]` and the gate is green with **zero** suppressions. Do NOT collapse the two `minimatch@^5` / `@^10` scopes into one global override: `brace-expansion` moved from a function export to an object export after 2.x, so a 5.x resolution under `minimatch@5.1.9` throws at require time — and it throws at *runtime*, so every gate including `check:generated` passes and the break ships latent (this happened once; see `eca02df`). `pnpm why` must be run with `-r` or the `@fel/contracts` instance is invisible. The chain does **not** end at #156: **#159** ([SECURITY] restore credential-safe durable job errors) was filed against it, because #156 reverted the `queue.fail` redaction, and was closed by **PR #160 @ `5ec4c08`**, which restored it via `redact_job_error_text`.
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
  - Merged after four review rounds. Final round fixed one blocker and three majors that the suite did not catch: the gross-profit identity inverted for contra-presented COGS, a normalizer-rejected row disabling identity checks for clean siblings, `wall_seconds_used` read latest-not-greatest, and the same polarity defect unfixed in `_check_rpo_balance`. M4 (redaction inside `stage_output`) is **FIXED by PR #156** @ `263bff8`. An earlier investigation here assessed it a false positive on the grounds that the frozen schemas intersect `_REDACT_KEYS` at exactly `{"text"}`. That reasoning was computed over the schema's *enumerated* property names, but `_redact` walks every key at **every depth**, and the frozen contract opens `dimensions` (`additionalProperties: {type: string}`) and `qualifiers` (`additionalProperties: true`) to arbitrary issuer-supplied names. A payload passing `validate_payload_item` with zero errors had `qualifiers.token` rewritten to `"[redacted]"` in the durable checkpoint, breaking `raw_payload_hash` on resume; end-to-end on real Postgres this produced two proposals with two hashes for one fact in one run. A top-level key named `raw` *is* rejected by the schema, so that part of the original doubt was correct.
  - Deliberately deferred out of the PR: **#153** (unify unit-case handling across identity, duplicate and definition checks — a one-sided fold was tried and reverted because it made a real break invisible) and **#154** (guidance range ordering: polarity-blind `check_range`, plus no ordering check at all for free-text `metric_id`s). Both move persisted identity keys and need an ADR.
  - Verified at merge: 1047 passed, 0 skipped against Postgres 17 + pgvector with `TEST_DATABASE_URL` set; five CI jobs green.
- **DOCS-ONBOARDING: PR #149 @ `52c787a` (2026-08-04) — issue #148.** Developer onboarding, architecture, system-design and testing guides. Landed after the refresh against `61058e4` and the integration-lead pass that executed every documented command; both are described under its Completed record below rather than repeated here.
- **Durable job-error sanitization: PR #160 @ `5ec4c08`.** Extends the redaction discipline to the durable job-error column. Closes the last sink where handler exceptions could carry issuer text or credentials into storage outside the treatment the event payloads already apply.

### Merged since 2026-08-04

Eight commits landed on `main` after `a25bf7c` (PR #152, the reconciliation that wrote the previous revision of this file). None of them was recorded here until now; the ledger sat at `5ec4c08` for sixteen days while trunk moved nine commits. Listed oldest first, in trunk order — note `a25bf7c` (2026-08-04) precedes `d44bb06` (2026-08-08), which is the reverse of the order the merge dates on the PRs suggest if read casually.

- **Measured test counts published: PR #163 @ `d44bb06` (2026-08-08).** `docs/development/testing.md` only. This closes the correction the DOCS-ONBOARDING record above demanded: the file said 861/186 and is now 258 JS/TS tests, **881 passed / 187 database-gated skipped** without a database, 1068 collected in total. It also disposes of the 873/187 figure quoted in #160's body, which reproduced against nothing. The counts are measured, not asserted — treat the file as the baseline and re-measure rather than quoting this bullet after further merges.
- **ADR-0010 proposed: PR #165 @ `ace7b83` (2026-08-08)** — `docs/decisions/ADR-0010-cross-repo-pattern-adoption.md`, +162/−0, **Status: Proposed**. It is a proposal and ratifies nothing; a second unratified ADR now sits alongside ADR-0009. It landed under shared `docs/decisions/**` carrying **no** label, where PR #145 took `contract-change` for exactly that surface — more evidence for #141, recorded below.
- **Advisory remediation: PR #167 @ `7eba341` (2026-08-11)** — js-yaml floor raised to `^4.3.1` (GHSA-5p4m-2wfm-xmqj) and nanoid patched to 3.3.18 (GHSA-2v37-7h3g-55p8), in `pnpm-lock.yaml` + `pnpm-workspace.yaml`. **This resolves the trunk red.** The `JS/TS — format, lint, typecheck, test, audit` check run is `failure` at `ace7b83` and `success` at `7eba341` and at every commit since, so the fail-closed `audit-bulk` gate that made every branch inherit a red job is cleared. Extends the #128 → #140 → #142 → #144 → #156 chain; like #165 it moves root shared paths unlabelled.
- **Relicense MIT → Apache-2.0: PR #166 @ `5394c64` (2026-08-11).** `LICENSE` +202/−21 and a new `NOTICE` +5. **The ledger had no record that the project's license changed; this is that record.** Verified rather than assumed: `LICENSE` is **byte-identical** to GitHub's canonical Apache-2.0 text (sha256 `c95bae1d1ce0235ecccd3560b772ec1efb97f348a79f0fbe0a634f0c2ccefe2c` for both), and `gh repo view --json licenseInfo` now reports `apache-2.0`. `NOTICE` reads "Financial Evidence Lab / Copyright 2026 H.J." and points at `LICENSE` for terms. Consequences a future reader should not have to rediscover: contributions from `5394c64` onward are under Apache-2.0, which adds an express patent grant and a NOTICE-propagation obligation that MIT did not impose, so any redistribution or vendoring path that was reasoned about under MIT terms needs re-checking, and the `NOTICE` file must travel with derivative distributions.
- **README Current-state reconcile: PR #168 @ `64eb571` (2026-08-11)** — refreshed `docs/handoff/README.md` against `ace7b83`. It was stale within hours and was stale when this entry was written: it described #162 and #164 as "in review, both unreviewed", #166 as merely *proposing* the relicense, `EVALS-REPORT-RENDER` as still reading `ready`, and trunk as red pending #167. All four were superseded the same day by the merges below. The lesson is the one this section exists to record: a Current-state block pinned to a SHA decays the moment the next PR lands.
- **FEL_EXTRACTION_MEMORY_STORES contract pinned: PR #170 @ `5f4d9b9` (2026-08-11) — issue #169 (closed).** +155/−1 in `workers/tests/test_entrypoint.py`. Pins the flag that discards all extraction output while jobs still report `succeeded` — the failure mode is silent data loss behind a green run, so the test is the only thing standing between that flag and a false success.
- **EVALS-REPORT-RENDER: PR #164 @ `a23514e` (2026-08-11) — issue #151 (closed).** Stdlib-only corpus-QA Markdown + SVG renderer in `evals/reporting/**` + `evals/tests/**`; both goldens committed, per the size-lever decision recorded below. **Two things the decision record got wrong, kept here rather than silently corrected:** the package merged at **+2531/−0 across 6 files**, roughly fourfold the ~640 changed lines projected (1161 of those lines are the test module and 255 the two goldens, so the "about 150 in fixtures, ~490 hand-written" split did not survive contact either). The `README.md` "below roughly 600 changed lines" figure remains a stated preference rather than a gate, so nothing was violated — but the estimate should not be reused as a planning input.
- **M3 normalize wiring: PR #162 @ `5b4b77c` (2026-08-11) — issue #155 (closed).** Wires `normalize/dimensions.py` and `normalize/currency.py` into the live pipeline and deletes the dead duplicate, with `extraction/types.py`, `validate/accounting.py`, `validate/pipeline.py`, `normalize/payload.py`, `normalize/pipeline.py`, `docs/architecture/system-design.md` and a new `workers/tests/extraction/test_dead_normalize_modules_wired.py` (+357) alongside. Closes the #155 entry carried under "Open issues carried but not queued" below.

**Trunk health at `5b4b77c`: green.** All five GitHub Actions check runs — `JS/TS`, `Python`, `DB — migration and backup-restore smoke`, `Web — Playwright E2E (fixture mode)`, `Secret scan (gitleaks)` — are `completed / success`. The `ace7b83` advisory-gate red is resolved by #167, so a red branch is now your own doing rather than inherited. One trap: the repository also carries `cursor`, `claude`, `supabase` and `vercel` check **suites** that sit permanently `queued` with a null conclusion. They are not gates and they never resolve — reading the suite list rather than the check runs will make green trunk look pending.

**Zero open PRs** as of 2026-08-20. Every package listed under Ready/Next below is therefore contending with nothing in flight.

### Tracker note — #96 residual owned by #108

Issue #96 remains **open** as a tracker only. Package `READER-CROSS-STACK` is `merged` via #105 for its `evals/**` mock/stack scope. Remaining acceptance **criterion #11** (production worker → Postgres → FastAPI → real `HttpEvidenceSource` → production Next.js reader + browser/hosted artifacts) is owned by **READER-PROD-SMOKE (#108)**. Do not re-dispatch #96; do not treat #96-open as blocking #57.

## Design gate (closed)

PR #102 merged to `main` @ `052836d`. Design gate is closed. Spec Kit packages, ADR-0006/0007, and recovered research are on trunk.

Still research-draft (not a dispatch blocker): recovered benchmark needs SEC timestamp/provenance/negative-case/range gates in the M2 compiler; recovered ontology needs citation/provenance fixes or explicit v1 exclusion.

## Active

None. DOCS-ONBOARDING (#148) merged as `52c787a` while this reconciliation was open; its record moved to Completed and its `workstreams.yaml` status is now `merged`, so its paths are free to claim.

Completed detail for DOCS-ONBOARDING, retained because it records what was verified rather than merely asserted:

   Refreshed against `61058e4`, which cleared what was previously recorded against it here: the six assertions that the M3 runtime was unmerged (including `system-design.md`'s "downstream code must not assume that PR's runtime is available on `main`"), four developer commands that could not run as written, `packages/ontology` missing from both the repository map and the static-check lists, the unreferenced `docs/runbooks/`, and the `eed2140` test-count baseline.

   A subsequent integration-lead pass **executed** every documented command rather than reading it, and corrected three further defects on-branch: `system-design.md` documented `available_at`, an identifier that exists nowhere in the schema or code (the real predicate is `published_at`); `local.md` claimed the HTTP source "fails startup" when it in fact fails closed at *request* time; and the `Typed roles (extraction/roles/)` heading credited `prompts/`, `schemas/` and `tools.py` to a directory holding only `__init__.py` and `base.py`. Also added the three CI gate commands that had no copy-pasteable form (`bandit`, `pip-audit`, `audit-bulk`), the two omitted `pyproject.toml` testpaths, and `.github/` + `.agents/` in the repository map. Verified correct and left alone: both start commands, the `uv --python 3.11` fallback, the three static-check dir lists (byte-identical to `ci.yml:99-101`), all 8 mermaid blocks, and the documented test counts, which reproduced exactly at `61058e4` (258 JS/TS; 861/186 without a DB; 1047/0 with one). They are now stale: #156 and #160 both added tests, and a run of this tree reports **881 passed / 187 skipped** without a database. `docs/development/testing.md` still says 861/186 and needs its own correction — note #160's body reports 873/187, which does not reproduce either.

## Ready

**Nothing is `ready` in `workstreams.yaml`.** The single `ready` entry, EVALS-REPORT-RENDER, merged via PR #164 and is now `merged`. Every item below is `blocked` there and is listed with its real gate, not as dispatchable work — do not start any of them on the strength of this heading. Two of them have satisfied dependencies and are one integration-lead decision away; that decision is not recorded here because it has not been made.

1. **M4-MODEL-CALC (#63)** — dependency satisfied and **uncontended**. `depends_on: [M3-EXTRACTION-CORE]`, merged at `61058e4`; `allowed_paths` are `packages/calculation-engine/**` alone, which overlap no other package and nothing in flight (zero open PRs). Branch `agent/m4-model-calc`. It has **no** `status` key and inherits `defaults.status: blocked`, so dispatching means **adding** a key. Of the packages with clear dependencies this is the one with no unresolved ruling attached — recorded as an observation for the integration lead, not as an authorization.
2. **M3-REVIEW (#61)** — dependency satisfied since #145 merged, so its `status: blocked` is **no longer a statement about dependencies**; the comment on that entry in `workstreams.yaml` now says so. Branch `agent/m3-review` (not yet created); paths `apps/web/**`, `apps/api/**`. It carries an **explicit** `status: blocked` key, so dispatching it means flipping that key rather than adding one. **What actually holds it:** #146 (terminal-run retry semantics, still open) should be resolved before #61 lands the producer, and the ADR-0009-vs-#157 fork should be ruled on before #61 exposes the SSE surface — #61 is the trigger that turns a false published guarantee into one a consumer relies on. Both are open; neither moved between 2026-08-04 and 2026-08-20.
3. **M3-CONFIDENCE-GATE (#62)** — **not** ready: it `depends_on: [M3-REVIEW]`, so it waits on #61 merging, not on #60. Also owns the live OpenAI adapter #60 deferred.

## Blocked (registered, not dispatchable)

Nine packages are `blocked` in `workstreams.yaml`. Only #108 is enumerated below because it is the only one with live, actionable blockers. The other eight — M3-REVIEW (#61) and M3-CONFIDENCE-GATE (#62), which appear under **Ready** above with their real gates, plus M4-FACT-SCENARIOS, M4-MODEL-CALC, M4-MODEL-UI, M5-BACKTEST, M5-FORECASTING and M5-AUDIT-RELEASE — have no blocker to clear beyond their dependencies. Seven of them inherit `defaults.status: blocked`; M3-REVIEW is the exception and carries the key explicitly. Recorded explicitly so a reader reconciling this file against the yaml per resume rule 2 is not left with eight unexplained entries.

1. **Blocked:** READER-PROD-SMOKE (#108) — branch `test/reader-prod-smoke`; child F of #87.
   - Blocker A: hosted deployment credentials not provisioned (request by name only; never claim ready).
   - Blocker B: known product residual — API `INTEGRITY_ERROR` classified as web `unavailable` (no integrity-alert UI kind); #108 must stop-and-escalate, not silently patch.
   - Flip to `ready` only after integration-lead provisions hosted secrets **and** clears the integrity residual (fix landed or explicit lead waiver).
   - Shared `.github/**` gated workflow requires separate integration-lead authorization before any smoke PR edits CI.

## Next (after ready merges)

1. **M3-REVIEW (#61)** has had its dependency satisfied since #145 merged — it was the only package waiting directly on #60. Branch `agent/m3-review` (not yet created; paths `apps/web/**`, `apps/api/**`). It carries an **explicit** `status: blocked` in `workstreams.yaml`; flip that one key to `ready` when dispatching, once the two rulings in item 3 are made. It was **not** flipped by the `5b4b77c` reconciliation: correcting a stale reason is a documentation fix, flipping a dispatch key is not.
2. **M3-CONFIDENCE-GATE (#62) is not yet unblocked.** `workstreams.yaml` gives it `depends_on: [M3-REVIEW]`, and `docs/handoff/README.md:26-28` makes a package ready only when *every* `depends_on` package is `merged` — so #62 waits on #61 landing, not on #60. It has **no** `status` key and inherits `defaults.status: blocked`, so dispatching it means adding a key rather than flipping one. #62 owns the live OpenAI adapter #60 deferred; note its `allowed_paths` do not currently include `packages/providers/**`, where the provider protocol lives.
3. **Rule on the ADR-0009 / #157 fork.** M4 itself needs no ruling — it was a real defect and PR #156 fixed it. What is still open is mutually exclusive: ADR-0009 (**Proposed**) would amend the six published "metadata-only" statements *down* to match the code, while **#157** adds the `steps.output` column so those statements stay true. Only one should land. #156 corrected four false statements in ADR-0009 but deliberately did not ratify it. **#158** (verify the restored checkpoint against a hash) is independent of the fork and needs no contract change.
4. **EVALS-REPORT-RENDER (#151) is done** — merged via PR #164 @ `a23514e`; issue closed. Its `evals/reporting/**` and `evals/tests/**` paths are free again, still as subtrees of the `evals/**` claimed by #108/#62/#67/#68, so serialize against whichever unblocks first. **M4-MODEL-CALC (#63)** is the uncontended candidate that replaces it in this slot; see Ready item 1.
5. **#153 and #154** — both deferred out of #145, both move persisted identity keys, both need an ADR before implementation.
6. READER-PROD-SMOKE (#108) remains blocked until credentials + the integrity residual are cleared.

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
- **#155** — **CLOSED** by PR #162 @ `5b4b77c` (2026-08-11): the two orphaned normalize modules are wired into the live pipeline and the dead duplicate is deleted. Retained here because the entry records how it was found — it was a direct #145 follow-up that appeared in *neither* handoff file's follow-up set (#146/#62/#153/#154/#157/#158), so the gap was in the ledger, not in the tracker.

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
