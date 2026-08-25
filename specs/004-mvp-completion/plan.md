# Implementation Plan: MVP Completion

**Branch**: `spec/004-mvp-completion` | **Date**: 2026-08-25 | **Spec**: [`spec.md`](./spec.md)

**Input**: Feature specification from `/specs/004-mvp-completion/spec.md`

> **Subordinate plan.** `specs/001-financial-evidence-lab/plan.md` remains the canonical implementation plan under the constitution. This file plans **release sequencing only** — the order in which already-specified packages are dispatched, and the preconditions each requires. It introduces no architecture and no requirement. Where the two disagree, `001/plan.md` governs. The constitutional disposition this requires is recorded as finding **C-1** in [`clarify-analyse.md`](./clarify-analyse.md).

## Summary

Nine registered packages and one unregistered workstream stand between `main` @ `5b4b77c` and the immutable MVP release artifact (`T0513`). Twenty-nine of sixty-seven in-scope Spec Kit tasks are outstanding. The critical path is six deep and terminates at `M5-AUDIT-RELEASE` (#68).

The technical approach is not new construction but **sequencing under two constraints the existing graph does not encode**: path-exclusivity between concurrently dispatched packages, and a credential precondition that no `depends_on` edge can express. The plan's substantive contribution is to make the second constraint explicit by registering `RELEASE-LIVE-CUTOVER` and giving #68 a dependency on it, so that the terminal node stops being unreachable.

## Technical Context

**Language/Version**: Python 3.11 (`.python-version`, `ruff`/`black`/`mypy` all pinned `py311`); Node 22 (`.node-version`); TypeScript with React 19

**Primary Dependencies**: Next.js 16 App Router; FastAPI + Pydantic modular monolith plus one Python worker; Supabase Postgres/pgvector ≥ 0.8.2, Auth, RLS, Storage; ECharts and React Flow. Per ADR-0002 (Accepted)

**Storage**: Supabase Postgres; `halfvec` embeddings ≤ 512 dimensions; jobs on a PostgreSQL table claimed `FOR UPDATE SKIP LOCKED` with heartbeat and stale-job reaper. Migrations frozen through `0005`; OpenAPI frozen at `v0.4.0`

**Testing**: pytest (`pythonpath` spanning `apps/api`, `workers/src`, `evals`, four `packages/*`); vitest for JS/TS; Playwright for web E2E; property, contract, golden-file and evaluation suites per parent §20.1

**Target Platform**: Railway hosts web, API and worker from one monorepo; GitHub Actions for CI and deployment gates

**Project Type**: Web application — modular monolith plus one worker process. No new services introduced by this plan

**Performance Goals**: 5,000-node p95 recalculation (`T0410`); retrieval Recall@10 ≥ 90.0% and the remaining nine parent §19.6 gates; forecast interval coverage 75–85%

**Constraints**: `defaults.credentials: mock-only` — **the binding constraint of this plan** (§5 of the spec). Path-exclusivity: no two concurrently dispatched packages may share an `allowed_paths` glob. Shared-path edits require `contract-change` plus an authorization record per #141. Contracts are frozen; this plan proposes no contract change

**Scale/Scope**: 10 packages, 29 tasks, 16 release-blocking issues, 8 dispatch waves. No new product surface

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Evidence and temporal-cutoff behavior is explicit and testable.** This plan adds no evidence path. It preserves the parent's temporal-validity gate (100%) as a release blocker and routes `T0112` — the only outstanding ingestion work — through `RELEASE-LIVE-CUTOVER` where cutoff behavior is already covered by the merged M1 test suites (`T0111`).
- [x] **Financial calculations are deterministic, decimal, typed, and source-linked.** Unchanged. `M4-MODEL-CALC` (#63) carries the decimal-engine and property-test obligations verbatim from `T0403`/`T0409`; this plan neither relaxes nor reinterprets them.
- [x] **Tests and numeric evaluation gates precede implementation tasks.** Wave 0 places the #171 regression test and the `tasks.md` reconciliation *before* any dispatch, so no package is built on a ledger that misreports its own dependencies' completion.
- [ ] **Tenant isolation, secrets, auditability, prompt-injection defenses, and cost ceilings are covered.** — **BLOCKED, see Complexity Tracking.** Cannot be asserted: every credential in `CREDENTIALS.md` reads "Not requested," so the approved secret-management flow required by constitution principle IV has never been exercised. This is the gap `RELEASE-LIVE-CUTOVER` exists to close, and it must be re-checked before wave 6.
- [ ] **The design stays within the approved modular-monolith stack or includes an approved complexity ADR.** — **BLOCKED, see Complexity Tracking.** The replace-OpenAI directive recorded in #132 substitutes `claude-opus-4-8` for the "OpenAI for generation" of ADR-0002 (Accepted), with no superseding ADR and no benchmark evidence. Constitution principle V requires both.

**Gate result: FAILS as of 2026-08-25.** Two of five checks cannot be asserted. Both failures are pre-existing conditions of the repository that this plan surfaces rather than introduces, and both have named remediations below. Per the constitution's Governance section a failed mandatory gate blocks merge — for *implementation* work. This plan is a planning artifact that proposes the remediation for both failures; ratifying it is the mechanism by which they get owners.

## Project Structure

### Documentation (this feature)

```text
specs/004-mvp-completion/
├── spec.md              # Release specification — what remains and against which gates
├── plan.md              # This file — release sequencing
└── clarify-analyse.md   # Clarification resolutions + cross-artifact analysis
```

No `research.md`, `data-model.md`, `quickstart.md` or `contracts/`: this feature adds no data model, no contract and no developer-facing entry point. No `tasks.md` **by deliberate choice** — the outstanding work already carries canonical IDs (`T0112`, `T0306`–`T0513`) in `specs/001-financial-evidence-lab/tasks.md`, and a second copy of those rows would reproduce the exact drift documented in spec §4.2.

### Source Code (repository root)

This plan modifies **no source code**. It sequences work against directories that already exist and whose ownership is already fixed by `allowed_paths`:

```text
apps/
├── web/                          # #61 M3-REVIEW, #65 M4-MODEL-UI, #66 M5-FORECASTING
└── api/                          # #61, #64 M4-FACT-SCENARIOS, #68 M5-AUDIT-RELEASE
workers/src/fel_workers/
├── extraction/                   # #62 M3-CONFIDENCE-GATE
└── forecasting/                  # #66, #67 M5-BACKTEST   (directory not yet created)
packages/
├── calculation-engine/           # #63 M4-MODEL-CALC, #64   (directory not yet created)
├── export/                       # #68                      (directory not yet created)
└── ui/                           # #65, #66
evals/                            # #62, #67, #68, RELEASE-LIVE-CUTOVER
docs/release/                     # #68                      (directory not yet created)
```

**Structure Decision**: No structural change. Five of the directories above (`workers/src/fel_workers/forecasting/`, `packages/calculation-engine/`, `packages/export/`, `docs/release/`) do not yet exist and are created by their owning package under ADR-0008's scaffold-registration exception, which permits the owning PR to carry the `pyproject.toml`, `Makefile` and `ci.yml` dir-list edits needed to make a new first-party package visible to the shared gates — **dir-list registration only**. Dependency additions remain outside that exception and require per-dispatch authorization.

## Phasing

Phases correspond to spec §6.2 waves. A wave opens only when every package in the prior wave is `merged`.

| Wave | Content | Opens when |
|---|---|---|
| 0 | Integration-lead actions: merge #172; fix #171 with a red-green test; reconcile 17 `tasks.md` boxes; register `RELEASE-LIVE-CUTOVER`; rule #146 and ADR-0009/#157; land the ADR for finding A-1; re-scope #134 | Now |
| 1 | #61 ∥ #63 (disjoint paths) | #61: after the two rulings. #63: now |
| 2 | #62 | #61 merged |
| 3 | #64 | #62 and #63 merged |
| 4 | #65, then #66 — serialized on `apps/web/**`, `packages/ui/**` | #64 merged |
| 5 | #67 | #66 merged |
| 6 | `RELEASE-LIVE-CUTOVER`, then #108 | Credentials provisioned; `evals/**` free |
| 7 | #68 | #67 and `RELEASE-LIVE-CUTOVER` merged |

Wave 0 is the only wave that can start today, and #63 is the only package dispatchable today.

## Complexity Tracking

> Two Constitution Check items fail. Both are pre-existing repository conditions, not complexity this plan introduces; both are recorded here because the template requires a justification for any failed check that a plan proceeds past.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle IV cannot be asserted: the approved secret-management flow has never been exercised (all five credential groups read "Not requested") | The parent's §19.6 gates and §26 item 2 require evaluation against real filings and a dual-adjudicated ≥300-question benchmark. No mock-only configuration can satisfy them, so the flow must be exercised before release | "Stay mock-only through release" was rejected because it makes `T0513` unachievable by construction — the terminal package cannot meet acceptance criteria its own inherited `credentials: mock-only` forbids. Deferring the check to wave 6 without registering an owner was rejected because that is the status quo that produced the gap |
| Principle V cannot be asserted: the replace-OpenAI directive (#132) substitutes an AI provider against ADR-0002 (Accepted) with no superseding ADR and no benchmark evidence | The directive is already recorded in an open issue and is shaping provider work; leaving it unreconciled means `RELEASE-LIVE-CUTOVER` would select a provider in violation of the constitution whichever way it chose | "Silently follow the directive" was rejected — principle V names additional AI providers explicitly and ADR-0002's change rule requires benchmark evidence that the current default fails a requirement. "Silently follow ADR-0002" was rejected because it contradicts a standing directive without surfacing the conflict. Only a superseding ADR resolves it |

Neither violation is remediated by this plan. Both are assigned owners by it: the first to `RELEASE-LIVE-CUTOVER` (spec §5.1), the second to a superseding ADR that must precede it (finding A-1).
