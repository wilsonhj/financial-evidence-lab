# Implementation Plan: MVP Completion

**Branch**: `spec/004-mvp-completion` | **Date**: 2026-08-25, refreshed 2026-08-31 | **Spec**: [`spec.md`](./spec.md)

**Input**: Feature specification from `/specs/004-mvp-completion/spec.md`

> **Subordinate plan.** `specs/001-financial-evidence-lab/plan.md` remains the canonical implementation plan under the constitution. This file plans **release sequencing only** — the order in which already-specified packages are dispatched, and the preconditions each requires. It introduces no architecture and no requirement. Where the two disagree, `001/plan.md` governs. The constitutional disposition this requires is recorded as finding **C-1** in [`clarify-analyse.md`](./clarify-analyse.md).
>
> **Branch prefix.** `spec/*` is not one of the prefixes `workstreams.yaml` exhibits (`agent/`, `contract/`, `feat/`, `fix/`, `chore/`, `test/`), and the constitution names `agent/*` for *implementation* work. `spec/*` is used here for a planning-only branch; if the integration lead prefers, rename to `agent/004-mvp-completion` or sanction `spec/*` as the planning prefix.

## Summary

Nine registered packages and **two** unregistered workstreams stand between trunk and the immutable MVP release artifact (`T0513`): the mock→live cutover (spec §5.1) and the migration-`0006` entry ADR-0011 requires for #157 (spec §4.4). Measured at `main` @ `a4bb356`; trunk is now `ebe77af` after PR #172. Twenty-nine of sixty-seven in-scope Spec Kit tasks are outstanding. The critical path is six deep and terminates at `M5-AUDIT-RELEASE` (#68).

The technical approach is not new construction but **sequencing under two constraints the existing graph does not encode**: path-exclusivity between concurrently dispatched packages, and a credential precondition that no `depends_on` edge can express. The plan's substantive contribution is to make the second constraint explicit by registering `RELEASE-LIVE-CUTOVER` and giving #68 a dependency on it, so the terminal node stops being unreachable.

## Technical Context

> **Deliberate omission.** Constitution principle V states the locked MVP stack "is recorded in `docs/decisions/ADR-0002-mvp-stack.md` and MUST NOT be restated elsewhere." `plan-template.md` nonetheless mandates a Technical Context block enumerating language, dependencies, storage and platform — so filling this section as written would restate the stack and breach principle V, inside the very section that then self-certifies stack compliance. This is a genuine template-versus-constitution conflict, recorded as finding **A-12**. It is resolved here by *pointing* rather than restating, and by keeping only the facts release sequencing actually depends on.

**Stack of record**: `docs/decisions/ADR-0002-mvp-stack.md` (Status: Accepted). Not restated here, per principle V.

**Language/Version**: Python 3.11 (`.python-version`; `ruff`, `black` and `mypy` all pinned `py311`); Node 22 (`.node-version`)

**Primary Dependencies**: per ADR-0002

**Storage**: per ADR-0002. Sequencing-relevant fact only: migrations are frozen through `0005` and OpenAPI at `v0.4.0`, so no package in any wave proposes a contract change

**Testing**: pytest, with `pythonpath` spanning `apps/api`, `workers/src`, `evals`, and four `packages/*` (`providers`, `retrieval`, `retrieval-evals`, `ontology`); vitest for JS/TS; Playwright for web E2E

**Target Platform**: per ADR-0002

**Project Type**: Web application — modular monolith plus one worker. **No new service, package or module is introduced by this plan**

**Performance Goals**: sequencing-relevant only — `T0410`'s 5,000-node p95 recalculation target gates #63, and the ten parent §19.6 gates gate #68

**Constraints**: `defaults.credentials: mock-only` — **the binding constraint of this plan** (spec §5). Path-exclusivity: no two concurrently dispatched packages may share an `allowed_paths` glob. **This PR is itself a `specs/**` shared-path change** and therefore carries `contract-change` plus an authorization record per #141; separately, it proposes no OpenAPI, JSON-schema or migration change

**Scale/Scope**: 11 packages (9 registered + 2 to register), 29 tasks, 14 release-blocking backlog issues, 8 dispatch waves. No new product surface

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Evidence and temporal-cutoff behavior is explicit and testable.** This plan adds no evidence path. It preserves the parent's 100% temporal-validity gate as a release blocker and routes `T0112` — the only outstanding ingestion work — through `RELEASE-LIVE-CUTOVER`, where cutoff behavior is already covered by the merged M1 suites (`T0111`).
- [x] **Financial calculations are deterministic, decimal, typed, and source-linked.** Unchanged. `M4-MODEL-CALC` (#63) carries the decimal-engine and property-test obligations verbatim from `T0403`/`T0409`; this plan neither relaxes nor reinterprets them.
- [x] **Tests and numeric evaluation gates precede implementation tasks.** Wave 0 placed the #171 red-green regression test before any package dispatch; it merged as PR #174 @ `a4bb356` on 2026-08-29, so this is now satisfied in fact rather than in plan. The `tasks.md` reconciliation remains outstanding but gates nothing.
- [ ] **Tenant isolation, secrets, auditability, prompt-injection defenses, and cost ceilings are covered.** — **FAILS.** Cannot be asserted: every credential group in `CREDENTIALS.md` reads "Not requested", so the approved secret-management flow required by principle IV has never been exercised. Re-check required before wave 6.
- [ ] **The design stays within the approved modular-monolith stack or includes an approved complexity ADR.** — **FAILS.** The replace-OpenAI directive in #132 substitutes `claude-opus-4-8` for ADR-0002's accepted "OpenAI for generation", with no superseding ADR and no benchmark evidence. Principle V requires both.

**Feature-specific check** (added because the five template items are the five Core Principles, and the clause this feature actually strains lives in Development and Review Workflow rather than in any principle):

- [ ] **Development and Review Workflow: `specs/001-financial-evidence-lab/` holds the sole canonical `spec.md`, `plan.md` and `tasks.md`.** — **FAILS.** This file is the repository's second `plan.md`. See finding **C-1**, which also records that `002/` and `003/` have each shipped their own `spec.md` and `tasks.md` since July, so a literal reading of "sole canonical" has not held for two months.

### Gate result

**FAILS — three of six.** The constitution's Governance section is unqualified: *"Unjustified complexity or a failed mandatory gate blocks merge."* It draws no distinction between implementation and planning artifacts, and this plan does not claim one.

Therefore: **this PR cannot be merged on its own authority.** Merging it requires an explicit integration-lead waiver recorded on the pull request, or prior remediation of the three failures. All three are pre-existing repository conditions that this plan surfaces and assigns owners to rather than introduces — but that is an argument for granting the waiver, not a reason the gate does not apply.

## Project Structure

### Documentation (this feature)

```text
specs/004-mvp-completion/
├── spec.md              # Release specification — what remains and against which gates
├── plan.md              # This file — release sequencing
└── clarify-analyse.md   # Clarification resolutions + cross-artifact analysis
```

No `research.md`, `data-model.md`, `quickstart.md` or `contracts/`: this feature adds no data model, no contract and no developer-facing entry point. No `tasks.md` **by deliberate choice** — the outstanding work already carries canonical IDs (`T0112`, `T0214b`, `T0306`–`T0513`) in `specs/001-financial-evidence-lab/tasks.md`, and a second copy would reproduce the drift documented in spec §4.2.

### Source Code (repository root)

This plan modifies **no source code**. It sequences work across directories whose ownership is already fixed by `allowed_paths`:

```text
apps/
├── web/                          # #61 M3-REVIEW, #65 M4-MODEL-UI, #66 M5-FORECASTING
└── api/                          # #61, #64 M4-FACT-SCENARIOS, #68 M5-AUDIT-RELEASE
workers/src/fel_workers/
├── extraction/                   # #62 M3-CONFIDENCE-GATE
└── forecasting/                  # #66, #67 M5-BACKTEST      (exists; __init__.py on trunk)
packages/
├── calculation-engine/           # #63 M4-MODEL-CALC, #64     (exists as .gitkeep; NOT on pythonpath)
├── export/                       # #68                        (absent from trunk)
└── ui/                           # #65, #66
evals/                            # #62, #67, #68, RELEASE-LIVE-CUTOVER
docs/release/                     # #68                        (absent from trunk)
```

**Structure Decision**: No structural change, and no new module. Two of the directories above are genuinely absent from trunk — `packages/export/` and `docs/release/` — and are created by `M5-AUDIT-RELEASE` (#68).

ADR-0008's scaffold-registration exception reaches **only** `packages/export/`, because the ADR scopes itself to "when a package's core deliverable is a new directory under `packages/**`". It does **not** reach `docs/release/` (a documentation tree, needing no registration) or `workers/src/fel_workers/forecasting/` (already inside `workers/src`, which is on `pythonpath`, and already present on trunk).

`packages/calculation-engine/` is a distinct case: the directory exists on trunk as a `.gitkeep` placeholder, but it is **absent from `pyproject.toml`**, so #63 still needs the ADR-0008 registration edits even though it creates no directory. The registration surface is the `pyproject.toml` and `Makefile` dir-lists, the `ci.yml` python-job dir-lists, and — per Amendment 1, ratified 2026-07-29 on merge of PR #147 — appending the package path to `infra/railway/worker.json`'s `buildCommand` install list, and only when the worker imports it. **Dir-list registration only.** Dependency additions (`requirements-dev.txt` and the `pyproject.toml` dependency tables) remain fully gated and require per-dispatch integration-lead authorization.

## Phasing

Wave contents are defined in **spec §6.2, which is authoritative**; this section states only the rules governing them, to avoid two divergent copies of the same list.

- Wave 0 is a set of integration-lead actions, not a package dispatch. It spans **several pull requests** (this one; the #171 fix, merged; the handoff reconciliation #172, merged; the `tasks.md` reconciliation; the `RELEASE-LIVE-CUTOVER` registration; the registration of ADR-0011's migration-`0006` entry for #157), which may land in any order — **except** that the last of these must precede #61's SSE surface, per ADR-0011's mandatory revisit trigger.
- Of wave 0, only the **#171 fix gated wave 1** — the defect #62 is later built to measure. **It merged 2026-08-29, so wave 1 is open.** The #146 and ADR-0009/#157 rulings that unblock #61 have both been made; what remains is implementation, not decision. #146's Option 1 gates #61 as a whole; #157's migration `0006` gates **only #61's SSE surface**, so a wave-1 #61 dispatch is non-SSE (spec §4.4, §6.2, §7).
- For package-bearing waves (1 onward), a wave opens only when every package in the prior wave reads `merged`.
- **`M4-MODEL-CALC` (#63) is wave-0-concurrent, and is now dispatched.** It is listed in wave 1 for dependency ordering, but requires no ruling and contends with nothing; PR #172 added its `status: ready` key on 2026-08-31.

## Complexity Tracking

> The template asks for justification of Constitution Check violations "that must be justified" — that is, complexity a plan *chooses*. This plan chooses none. The entries below are **pre-existing gate failures** the plan inherits and assigns owners to; they are recorded here because the template offers no other place to disclose a failed check, and disclosing them is preferable to leaving the failures unexplained.

| Violation | Why it stands | Simpler Alternative Rejected Because |
|-----------|---------------|-------------------------------------|
| Principle IV: the approved secret-management flow has never been exercised (all five credential groups read "Not requested") | The parent's §19.6 gates and §26 item 2 require evaluation against real filings and a dual-adjudicated ≥300-question benchmark; no mock-only configuration satisfies them | "Stay mock-only through release" makes `T0513` unachievable by construction — the terminal package cannot meet acceptance criteria its inherited `credentials: mock-only` does not provide for. "Defer to wave 6 without an owner" is the status quo that produced the gap |
| Principle V: the replace-OpenAI directive (#132) substitutes an AI provider against ADR-0002 (Accepted) with no superseding ADR and no benchmark evidence | The directive is recorded in an open issue and is already shaping provider work; unreconciled, `RELEASE-LIVE-CUTOVER` would violate the constitution whichever provider it chose | "Silently follow the directive" breaches principle V, which names additional AI providers explicitly. "Silently follow ADR-0002" contradicts a standing directive without surfacing it. Only a superseding ADR resolves it |
| Development and Review Workflow: this is the repository's second `plan.md` | The feature needs a sequencing artifact, and `/speckit.plan` produces exactly this file | "Drop `plan.md` and follow the 002/003 precedent" was offered and declined (Q-4). "Amend the constitution first" remains available and is arguably cheapest, since one MINOR amendment would also retroactively legitimise `002/` and `003/` — see C-1 |

Remediations, in order: land the A-1 ADR; register `RELEASE-LIVE-CUTOVER` and provision credentials; rule C-1 (waiver, amendment, or drop `plan.md`).
