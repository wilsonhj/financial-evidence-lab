# M3 Completion — Agentic Extraction, Remaining Work

**Status:** Draft for integration-lead ratification
**Version:** 1.0.0
**Date:** 2026-08-31
**Parent specification:** `specs/001-financial-evidence-lab/spec.md` v1.2 (governs on conflict)
**Feature specification:** `specs/003-agentic-extraction/` — the M3 design. This document adds no design; it sequences what 003 already specifies and records the gates 003 predates.
**Scope:** `T0306`–`T0310`, delivered as `M3-200`–`M3-204` (#61) and `M3-300`–`M3-304` (#62).
**Baseline measured:** `origin/main` @ `ebe77af`
**Canonical task ledger:** `specs/001-financial-evidence-lab/tasks.md`. This directory ships **no `tasks.md`** — the work already carries canonical IDs, and 003 already carries the milestone-scoped ones.

---

## 1. Purpose and standing

M3's exit criterion, from parent §21: **"reviewers can trace, approve, correct, and version extractions without source ambiguity."**

`specs/003-agentic-extraction/` specifies *how*. This document answers a narrower question that 003 cannot, because 003 was written before the gates existed: **what must happen, in what order, before #61 and #62 can be dispatched at all** — and it records one gate that makes M3 unreachable in the repository's current configuration (§5).

Subordinate to 001 and to 003 under constitution v1.2.0. It introduces no requirement not already traceable to one of them.

### 1.1 What this document does not do

It authorizes nothing. Flipping a `status`, provisioning a credential, and ratifying an ADR remain integration-lead actions. §8 lists what is owed.

---

## 2. Evidence basis

Every count, status and identifier was produced by a command run against `origin/main` @ `ebe77af` on 2026-08-31. Statements of judgement are marked where they appear.

| Claim | Command |
|---|---|
| Trunk, CI | `git log -1 origin/main`; `gh run list --branch main` |
| Package status | `git show origin/main:docs/handoff/workstreams.yaml` |
| M3 task state | `git show origin/main:specs/001-financial-evidence-lab/tasks.md`; `specs/003-agentic-extraction/tasks.md` |
| Open work | `gh issue list --state open --limit 100` |
| Credentials | `git show origin/main:docs/handoff/CREDENTIALS.md` |
| Exit criterion | parent `spec.md` §21, Milestone 3 |

---

## 3. Verified state

- Trunk at the 2026-08-31 measurement: `ebe77af`, five of five checks passing. Trunk has since moved to `b8dc8a6` (#175, #173, #183) and its JS/TS audit gate is red on a `fast-uri` advisory batch unrelated to this document; every count below was re-verified against `b8dc8a6` on 2026-09-03 and none changed.
- Packages: **32 registered — 23 `merged`, 1 `ready`, 8 not started.** Two more await registration (§4.3).
- M3 core (`M3-EXTRACTION-CORE`, #60) merged @ `61058e4`. `T0301`–`T0305` are delivered but still read `[ ]` in the canonical ledger — one of the 17 drifted checkboxes.
- **M3 remaining: 5 canonical tasks, 10 milestone tasks, 2 packages.**

| Package | Issue | Canonical | Milestone tasks | Paths |
|---|---|---|---|---|
| `M3-REVIEW` | #61 | T0308, T0309 | M3-200 … M3-204 | `apps/web/**`, `apps/api/**` |
| `M3-CONFIDENCE-GATE` | #62 | T0306, T0307, T0310 | M3-300 … M3-304 | `workers/src/fel_workers/extraction/**`, `workers/tests/**`, `evals/**` |

---

## 4. What must happen before dispatch

### 4.1 Two rulings, both now made

| Gate | Ruling |
|---|---|
| **#146** — job retries can outlive a run's terminal state | **Option 1, terminal runs are final**, ruled 2026-08-29. Consumer must drop or dead-letter a job whose `extraction_runs` row is `succeeded`/`failed`/`cancelled`. **Not implemented** — still a producer gate for #61 |
| **ADR-0009 vs #157** | **Ruled** — ADR-0011 accepted, ADR-0009 superseded. The `extraction_run_steps.output` column is the sanctioned fix |

### 4.2 The ADR-0011 scope ruling

ADR-0011 is internally inconsistent about how much of #61 the `0006` work blocks: its header says "Blocks: #61 **SSE** until the *implementing* PR for migration 0006 lands"; its Consequences say "Add this work to #61's `depends_on`".

**Ruled 2026-08-31: the header governs.** The `0006` work blocks **only #61's SSE surface**, not the package. Consequences:

- #61 is dispatchable **non-SSE** without waiting for `0006`.
- The critical path stays **6 deep**; it would have become 7 under the other reading, with wave 1 holding #63 alone.
- #61's PR must not expose the SSE surface. That is a review gate on #61, not a dependency edge, and `workstreams.yaml` carries no such edge.

Recorded here so a later reader who notices the Consequences clause does not re-open a settled question.

### 4.3 Two package registrations owed

Neither exists in `workstreams.yaml`. Both are prepared on `chore/register-live-cutover-and-0006` and land `blocked`.

| Package | Owns | Why it gates M3 |
|---|---|---|
| migration-`0006` entry (#157) | The `extraction_run_steps.output` column, per ADR-0011 | Gates #61's SSE surface. **Contends with #62** on `workers/src/fel_workers/extraction/**` and `workers/tests/**` — the two can never run concurrently |
| `RELEASE-LIVE-CUTOVER` | Provisioning + live evaluation; `T0112`, #132, #81, #137 | Gates `M3-304` — see §5 |

### 4.4 Four correctness defects that #62 is built to measure

`M3-303` requires evaluating **99% numeric accuracy**. These degrade exactly that, so they precede it:

| Issue | Effect |
|---|---|
| #153 | Unit-case handling diverges across identity, duplicate and definition checks |
| #154 | Polarity-blind `check_range`; no ordering check for free-text `metric_id`s |
| #158 | Crash-resume restores a checkpoint without verifying the payload against any hash |
| #133 | Numeric identity tautology in unit tests — a test-validity defect behind the accuracy gate |

#153 and #154 move persisted identity keys and need an ADR before implementation.

---

## 5. M3 cannot complete in the repository's current configuration

**`M3-304` requires a live provider credential.** Verbatim from `specs/003-agentic-extraction/tasks.md`:

> **M3-304** Run live OpenAI structured-output smoke with approved secret, provider-failure suite, `make ci`, independent review, and publish immutable eval report.

Against that:

1. `docs/handoff/CREDENTIALS.md` lists five credential groups. **All five read "Not requested."**
2. `workstreams.yaml:73` sets `defaults.credentials: mock-only`. `M3-CONFIDENCE-GATE` (#62) has **no `credentials:` key**, so it inherits mock-only.
3. Only `READER-PROD-SMOKE` (#108) overrides it.

**This is the same structural defect `specs/004-mvp-completion/` §5 identifies for `M5-AUDIT-RELEASE`, and it bites two milestones earlier than that document says.** 004 frames mock-only as blocking the *release*; it blocks the *next milestone*.

### 5.1 And the credential named is contested

`M3-304` says *OpenAI*. Issue #132's replace-OpenAI directive says `claude-opus-4-8`. ADR-0002 (Accepted) says "OpenAI for generation". Constitution principle V requires an approved ADR **and benchmark evidence** for any AI-provider substitution, and neither exists — so `M3-304` cannot be executed against any provider without violating something. This is finding **A-1** in `specs/004-mvp-completion/clarify-analyse.md`; **ADR-0012 (Proposed)** is drafted to resolve it.

Note the embeddings asymmetry #132 records: Anthropic ships no embeddings endpoint, so index-build and query embedding cannot use Claude regardless. An OpenAI credential may be required even if generation moves.

### 5.2 Required resolution

Give #62 an explicit `credentials:` override, and sequence `RELEASE-LIVE-CUTOVER` before `M3-304` — or rule that `M3-304` is deferred and M3 exits without it, which is a scope decision, not an inference this spec should make.

---

## 6. Dispatch sequence

`docs/handoff/README.md` forbids scheduling two packages with overlapping `allowed_paths` concurrently.

| Wave | Content | Opens when |
|---|---|---|
| **0** | ~~Merge #175, #173~~ (done 2026-08-31); ~~ratify constitution 1.2.0~~ (done 2026-09-03, PR #183); merge the registration PR (#185) and ADR-0012 (#186); implement #146 Option 1; fix #153, #154, #158 (PR #208), #133 (PR #210); reconcile `tasks.md` (PR #206) | Now. Lead actions across several PRs |
| **1** | **#61 (non-SSE)** ∥ **#63** — disjoint (`apps/**` vs `packages/calculation-engine/**`) | #146 implemented |
| **2** | migration-`0006` (#157) | Registered; **must not overlap #62** |
| **3** | `RELEASE-LIVE-CUTOVER` | Credentials provisioned; ADR-0012 ruled; **must not overlap #62** (`evals/**`) |
| **4** | **#62** including `M3-304` | #61 merged, `0006` merged, cutover merged |

`#62` is placed after `0006` rather than beside it because they share two path globs. `#63` belongs to M4 but is `ready` on trunk and contends with nothing, so it runs alongside M3 throughout.

### 6.1 Measured contention among the M3 packages

| Pair | Result |
|---|---|
| #61 ∥ #63 | disjoint |
| #61 ∥ #62 | disjoint (`apps/**` vs `workers/**`, `evals/**`) |
| #62 ∥ `0006` entry | **contends** — `workers/src/fel_workers/extraction/**`, `workers/tests/**` |
| #62 ∥ `RELEASE-LIVE-CUTOVER` | **contends** — `evals/**` |

> **Method caveat.** Exact-string comparison of globs; it does not detect subtree containment. `#108` claims `workers/**`, which *contains* `workers/tests/**`.

---

## 7. Exit criteria

M3 exits when parent §21 is satisfied — *"reviewers can trace, approve, correct, and version extractions without source ambiguity"* — evidenced by:

- **#61**: run create/get/list/cancel/rerun APIs with resumable SSE, auth, idempotency, cutoff validation (M3-200); atomic accept/edit/reject/merge/bulk with a required expected version per proposal, plus If-Match correction/history (M3-201); immutable approved versions with evidence manifests and an M4-ready read contract (M3-202); accessible execution graph, evidence review, blockers/conflicts, batch actions, history UI (M3-203); RLS, temporal, race, merge, SSE-replay, accessibility and browser tests (M3-204).
- **#62**: versioned adjudicated dataset and deterministic `isotonic-v1` calibrator, fail-closed on insufficient data (M3-300); calibrated confidence with owner-only audited 0.85/0.80 policy (M3-301); proof that nothing auto-approves through any API, worker, bulk, replay or policy path (M3-302); exact guidance and KPI/driver matching plus 99% numeric accuracy, referencing M2's contradiction report rather than adding a detector (M3-303); the live smoke and immutable eval report (M3-304, §5).

Each package additionally owes `defaults.required_evidence`: tests, telemetry where applicable, documentation, acceptance notes.

---

## 8. Owed by the integration lead

Struck items were completed after this document was drafted; they are kept so the
sequence stays legible rather than silently renumbered.

1. ~~Merge #175, then #173.~~ Both merged 2026-08-31 (`f158e05`, `fdcb3d2`).
2. Review and merge the registration PR #185 (`chore/register-live-cutover-and-0006`) — both entries `blocked`.
3. Rule **ADR-0012** (Proposed, PR #186) — until then `M3-304` has no lawful provider.
4. ~~Ratify **constitution 1.2.0**.~~ Ratified 2026-09-03 (PR #183 @ `b8dc8a6`), which is what permits this directory's subordinate `spec.md` and `plan.md`.
5. Provision the credential `M3-304` needs, or rule it deferred (§5.2).
6. Schedule implementation of **#146 Option 1** — the last gate on #61. In progress on `fix/146-terminal-runs-final`, together with #204.
7. Reconcile `tasks.md` — 17 checkboxes, `T0215` caveat. PR #206 does this: 16 flipped, `T0112` and `T0215` deliberately left with the reason recorded on each line.
8. Ratify or return this spec.

---

## 9. Risks

| Risk | Evidence | Mitigation |
|---|---|---|
| M3 unreachable in mock-only mode | §5; all five credential groups "Not requested" | Register `RELEASE-LIVE-CUTOVER`; give #62 a `credentials:` override |
| `M3-304`'s provider is contested | ADR-0002 vs #132; principle V unsatisfied | ADR-0012 |
| #62 measures a validator with known defects | #153, #154, #158, #133 open | Fix before `M3-303` |
| `0006` and #62 contend | Both claim two globs | Wave 2 before wave 3; never concurrent |
| A reader re-opens the settled SSE scope | ADR-0011 contradicts itself | §4.2 records the ruling and the alternative |
| Ledger says M3-core unstarted | `T0301`–`T0305` read `[ ]` | Reconcile |
| Suppression lower bound untested | Full suite passes with the mechanism deleted | Test-only fix; filed |

---

## 10. Summary

| Measure | Value |
|---|---|
| Canonical tasks remaining | **5** (T0306–T0310) |
| Milestone tasks remaining | **10** (M3-200…204, M3-300…304) |
| Packages | **2** (#61, #62) + 2 to register |
| Rulings made | 3 (#146, ADR-0009/#157, ADR-0011 scope) |
| Rulings owed | 1 (ADR-0012) + credential decision |
| Correctness defects gating `M3-303` | 4 |
| Dispatchable today | **#61 non-SSE**, once #146 is implemented; **#63** now |
| Blocking gate with no owner until registered | `M3-304`'s credential |
