# Implementation status

Last updated: 2026-08-03

## Repository

- Default and implementation base: `main`.
- Current `origin/main` tip: `eed2140` (#144 postcss/brace-expansion advisory remediation, stacked on #142). Always resolve trunk against `origin/main`.
- **`89e4363` does NOT land with PR #145.** It reached the remote only via `agent/m3-extraction-core` and was **reverted on that branch by `7f11bab`**, per the integration-lead ruling recorded on #60: it amends the constitution (1.1.0 -> 1.2.0), rewrites `AGENTS.md` document precedence, and flips 14 task checkboxes including 12 lead-reserved ones — all `shared_paths`, with no `contract-change` label and no ADR. Verified byte-identical to `origin/main` on both sides of the revert. Re-landing it requires its own `contract-change` PR (#141). This line previously said it "lands with PR #145" — true when written, wrong after the revert.
- In review: M3-EXTRACTION-CORE (#60) on `agent/m3-extraction-core` (PR #145). Next dispatch after it merges is M3-REVIEW (#61).
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

### Tracker note — #96 residual owned by #108

Issue #96 remains **open** as a tracker only. Package `READER-CROSS-STACK` is `merged` via #105 for its `evals/**` mock/stack scope. Remaining acceptance **criterion #11** (production worker → Postgres → FastAPI → real `HttpEvidenceSource` → production Next.js reader + browser/hosted artifacts) is owned by **READER-PROD-SMOKE (#108)**. Do not re-dispatch #96; do not treat #96-open as blocking #57.

## Design gate (closed)

PR #102 merged to `main` @ `052836d`. Design gate is closed. Spec Kit packages, ADR-0006/0007, and recovered research are on trunk.

Still research-draft (not a dispatch blocker): recovered benchmark needs SEC timestamp/provenance/negative-case/range gates in the M2 compiler; recovered ontology needs citation/provenance fixes or explicit v1 exclusion.

## Active

1. **In review:** M3-EXTRACTION-CORE (#60) — branch `agent/m3-extraction-core`, PR **#145** OPEN from `main` @ `eed2140`, carrying the `contract-change` label (`docs/decisions/**` addition, `AGENTS.md:41`). No review submitted, because GitHub disallows self-approval — `reviewDecision` is empty despite every blocker below having been raised and resolved on-branch.

   Scope delivered: `packages/ontology` saas-metrics/v1 (14 metrics / 9 families), bounded durable extraction workflow (budgets, checkpoints, five typed roles), Decimal normalize/validate, `extraction_run` consumer dispatch, proposals always `needs_review`.

   Review remediation on-branch, by round: numeric parser truncation (`4200000` → `420`); evidence truncated to 64 chars on resume; mock model bound unconditionally in the production entrypoint; worker packaging; budget reset per retry; runs stuck `running` after untyped escapes. Then the magnitude/scale round — the suffix table (`bn`/`MM`/`trillion`), partial numbers failing closed, the declared `scale` validated instead of collapsed to 0 (mantissa + exponent per the frozen fixture, ADR-0001), `sign` cross-checked against the value, and the step commit made atomic with its output-carrying event. Then durability defaults, `citation_status` from evidence rather than model output, currency in the comparability key, and refusing to attach to an adjudicated conflict. Then the accounting-cluster round: the gross-profit identity inverted for parenthesized (negative) COGS and the same polarity bug in cRPO/RPO; a normalizer-rejected row silently disabling identities for its clean siblings; and `wall_seconds_used` read latest-wins rather than `MAX`. Finally the checkpoint payload: substitution inside `stage_output` corrupting `raw_payload_hash` for issuer keys named like secrets, and the event/log redaction helpers split so telemetry cannot inherit the carve-out.

   Two defects found by the first real-Postgres coverage: four of five terminal paths never wrote their terminal event (0004 rejects child inserts once a run row is terminal), and content-triggered mock controls (`ABSTAIN`/`REFUSE`) were reachable from untrusted filing text.

   Known gaps left open deliberately, with issues: **#153** (unit-case handling — the identity slice keys on the raw string, so `usd`/`USD` skip the check; the one-sided fold was tried and reverted as net-harmful, and unifying it touches the persisted conflict identity); **#146** (terminal-run retry semantics); **#62** (live OpenAI adapter); and the `steps.output` column that ADR-0009 names as the correct fix for the checkpoint-in-event-stream trade.

   Move this record into **Completed** when PR #145 lands, and flip `workstreams.yaml` `status: review` -> `merged` with the merge SHA.

Serialization notes: blocked #108 overlaps `apps/api/**` + `apps/web/**` + `evals/**` — if #108 unblocks, do not run it concurrently with any package holding those paths.

## Ready

None — #61 and #62 both depend on #60, which has not merged yet.

On #145 merging, M3-REVIEW (#61) becomes ready (branch `agent/m3-review`, not yet created; paths `apps/web/**`, `apps/api/**`), then M3-CONFIDENCE-GATE (#62), which also owns the live OpenAI adapter #60 deferred. Flip both `status:` keys in `workstreams.yaml` at the same time — they currently inherit `defaults.status: blocked`.

## Blocked (registered, not dispatchable)

1. **Blocked:** READER-PROD-SMOKE (#108) — branch `test/reader-prod-smoke`; child F of #87.
   - Blocker A: hosted deployment credentials not provisioned (request by name only; never claim ready).
   - Blocker B: known product residual — API `INTEGRITY_ERROR` classified as web `unavailable` (no integrity-alert UI kind); #108 must stop-and-escalate, not silently patch.
   - Flip to `ready` only after integration-lead provisions hosted secrets **and** clears the integrity residual (fix landed or explicit lead waiver).
   - Shared `.github/**` gated workflow requires separate integration-lead authorization before any smoke PR edits CI.

## Next (after ready merges)

1. M3-EXTRACTION-CORE (#60) — delivered on `agent/m3-extraction-core`; awaiting merge of PR #145. Then #61, then #62.
2. READER-PROD-SMOKE (#108) remains blocked until credentials + integrity residual cleared (does **not** gate #60).

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
