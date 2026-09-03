# Implementation Plan: M3 Completion

**Branch**: `spec/005-m3-completion` | **Date**: 2026-08-31 | **Spec**: [`spec.md`](./spec.md)

**Input**: Feature specification from `/specs/005-m3-completion/spec.md`

> **Subordinate plan**, permitted by constitution v1.2.0. `specs/001-financial-evidence-lab/plan.md` is the parent and governs on conflict; `specs/003-agentic-extraction/` holds the M3 design. **Wave contents are defined in `spec.md` §6, which is authoritative** — this file states only the gate result and the rules governing sequencing, so the same list does not exist twice and drift independently.

## Summary

Two packages stand between `ebe77af` and M3's exit criterion: `M3-REVIEW` (#61) and `M3-CONFIDENCE-GATE` (#62), carrying five canonical tasks as ten milestone tasks that `specs/003-agentic-extraction/` already specifies.

The plan's contribution is not design. It is the observation that **M3 is unreachable in the repository's current configuration** — `M3-304` requires a live provider credential, none is provisioned, #62 inherits `mock-only`, and the provider it names is contested by a directive with no ADR behind it. `specs/004-mvp-completion/` identifies the same gap but places it at M5; it arrives at M3.

## Technical Context

> **Deliberate omission.** Constitution principle V states the locked stack "MUST NOT be restated elsewhere". Only sequencing-relevant facts appear below.

**Stack of record**: `docs/decisions/ADR-0002-mvp-stack.md` (Accepted), except its provider clause, which `ADR-0012` (Proposed) would supersede — see spec §5.1

**Language/Version**: Python 3.11; Node 22

**Storage**: migrations frozen through `0005`. **M3 requires `0006`** (`extraction_run_steps.output`, per ADR-0011) — the only contract movement in this milestone

**Testing**: pytest; vitest; Playwright. `M3-204` adds RLS, temporal, race, merge, SSE-replay, accessibility and browser suites

**Project Type**: web application — no new service, package or module

**Performance Goals**: none specific to M3 beyond the parent gates

**Constraints**: `defaults.credentials: mock-only` — **the binding constraint** (spec §5). Path-exclusivity: the `0006` entry and #62 share two globs and can never run concurrently. This PR is itself a `specs/**` shared-path change and carries `contract-change` plus an authorization record per #141

**Scale/Scope**: 2 packages, 5 canonical tasks, 10 milestone tasks, 2 registrations, 5 waves

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Evidence and temporal-cutoff behavior is explicit and testable.** Unchanged from 003; `M3-200` carries cutoff validation and `M3-204` tests it.
- [x] **Financial calculations are deterministic, decimal, typed, and source-linked.** M3 proposes values for human review; it computes no authoritative financial result.
- [x] **Tests and numeric evaluation gates precede implementation tasks.** Wave 0 places #153, #154, #158 and #133 before `M3-303`, so the 99%-accuracy gate is not measured against a validator with known defects.
- [ ] **Tenant isolation, secrets, auditability, prompt-injection defenses, and cost ceilings are covered.** — **FAILS (A-1).** The approved secret-management flow has never been exercised; all five credential groups read "Not requested", and `M3-304` requires one.
- [ ] **The design stays within the approved modular-monolith stack or includes an approved complexity ADR.** — **FAILS (A-2).** The provider substitution directed by #132 has neither an approved ADR nor benchmark evidence. ADR-0012 is drafted, not ratified.

### Gate result

**FAILS — two of five.** The Governance clause is unqualified: *"Unjustified complexity or a failed mandatory gate blocks merge."* Merging this specification therefore requires an integration-lead waiver recorded on the PR, or prior remediation. Both failures are pre-existing conditions this plan surfaces rather than introduces — an argument for granting the waiver, not a reason the gate does not apply.

## Project Structure

### Documentation (this feature)

```text
specs/005-m3-completion/
├── spec.md              # What remains for M3, the gates, and the dispatch sequence
├── plan.md              # This file — gate result and sequencing rules only
└── clarify-analyse.md   # Four lead rulings + eight analysis findings
```

No `tasks.md`: `specs/003-agentic-extraction/tasks.md` already carries `M3-200`–`M3-304` mapped onto `T0306`–`T0310`, and constitution v1.2.0 permits a subordinate ledger only where it does not restate an existing one. This one would.

### Source Code (repository root)

No source change. Directories are already owned by `allowed_paths`:

```text
apps/web/, apps/api/                          # #61
workers/src/fel_workers/extraction/           # #62, and the 0006 entry — CONTENDED
workers/tests/                                # #62, and the 0006 entry — CONTENDED
evals/                                        # #62, and RELEASE-LIVE-CUTOVER — CONTENDED
db/migrations/, packages/contracts/           # the 0006 entry only
```

**Structure Decision**: no structural change and no new module. The only new directory in M3 is none; `0006` adds a migration file and a `db/migrations/tests/` harness beside the existing ones, which ADR-0008's scaffold exception does not reach and does not need to — neither is a new first-party package.

## Sequencing rules

Wave contents: **`spec.md` §6.** Rules:

- Wave 0 is lead actions across several PRs and may land in any order, except that **#146's implementation gates wave 1** and the four correctness fixes gate wave 4 (`#62` / `M3-304`).
- A package-bearing wave opens only when every package in the prior wave reads `merged`.
- **#62 must never be concurrent with the `0006` entry** — two shared globs.
- **#63 is wave-independent.** It belongs to M4, reads `status: ready` on trunk, contends with nothing, and can run beside any M3 wave.

## Complexity Tracking

> The template asks for justification of violations a plan *chooses*. This plan chooses none; both entries are inherited gate failures, recorded because the template offers no other place to disclose one.

| Violation | Why it stands | Simpler alternative rejected because |
|-----------|---------------|--------------------------------------|
| Principle IV: the secret flow has never been exercised | `M3-304` requires a live provider smoke and an immutable eval report; no mock configuration produces either | "Complete M3 mock-only" makes `M3-304` unachievable by construction. "Defer `M3-304`" is defensible but is a scope decision for the lead, not an inference — spec §5.2 |
| Principle V: the provider substitution has no ADR and no benchmark evidence | #132 is a standing directive already shaping provider work; unreconciled, `M3-304` violates something whichever provider it uses | "Follow the directive" breaches principle V. "Follow ADR-0002" contradicts a standing directive. Only a superseding ADR resolves it — ADR-0012 |

Remediations, in order: ratify ADR-0012; register `RELEASE-LIVE-CUTOVER` and provision or formally defer `M3-304`'s credential.
