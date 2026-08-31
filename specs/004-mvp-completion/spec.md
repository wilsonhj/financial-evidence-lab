# MVP Completion — Release Specification

**Status:** Clarified; awaiting integration-lead ratification
**Version:** 1.0.0
**Date:** 2026-08-25
**Parent specification:** `specs/001-financial-evidence-lab/spec.md` v1.2
**Scope:** T0306–T0310, T0401–T0410, T0501–T0513 (excluding the deferred T0506), plus T0214b and the residual T0112 — **29 tasks**. No new product surface.
**Baseline measured:** `origin/main` @ `a4bb356`, CI green (refreshed 2026-08-30; first drafted against `5b4b77c`). Trunk has since advanced to `ebe77af` (PR #172, docs-only); §3 records the two counts that moved with it.
**Canonical task ledger:** `specs/001-financial-evidence-lab/tasks.md`. **This feature directory deliberately ships no `tasks.md`** — see §1.2.

---

## 1. Purpose and standing

### 1.1 Purpose

Answer one question with evidence: **what remains before Financial Evidence Lab can produce the immutable MVP release artifact defined in `T0513`?**

`spec.md` v1.2 defines *what the product is*. This document defines *what is left, in what order, and against which gates*. It introduces no requirement not already traceable to the parent spec.

### 1.2 Standing relative to the canonical feature directory

This directory is **subordinate** to `specs/001-financial-evidence-lab/`, which the constitution names as holding the sole canonical `spec.md`, `plan.md`, and `tasks.md`.

- It defines **no new requirements**. Every gate cited here is quoted from parent §19.5, §19.6 or §26.
- It ships **no `tasks.md`**. The 29 outstanding units of work already carry canonical IDs (`T0112`, `T0214b`, `T0306`–`T0513`) in the parent ledger. A fourth copy of those rows would drift exactly as §4.2 documents — that risk is the single most load-bearing finding in this spec, and duplicating the ledger to describe it would be self-defeating.
- It does not follow `.specify/templates/spec-template.md`. That template marks "User Scenarios & Testing", "Requirements" and "Success Criteria" as mandatory; this document has none of them, because it specifies no product behaviour — it inventories work already specified elsewhere and sequences it. The omission is deliberate and declared here rather than left for a reader to discover.
- The constitution's "sole canonical" clause is **already strained by existing practice, not first by this directory**: `002-observable-hybrid-retrieval/` and `003-agentic-extraction/` have each shipped their own `spec.md` and `tasks.md` since July 2026, and the clause speaks of "*the* active Spec Kit feature directory" in the singular where four now exist. See **C-1**.
- Its `plan.md` is a **release-sequencing plan**, not a competing implementation plan. Where it and `001/plan.md` disagree, `001/plan.md` governs. See `clarify-analyse.md` finding **C-1** for the constitutional disposition this requires from the integration lead.

### 1.3 What this document does not do

It authorizes nothing. Flipping any package `status`, provisioning any credential, and ratifying any ADR remain integration-lead decisions. §8 lists what is still owed.

---

## 2. Evidence basis

Every **count, status and identifier** below was produced by a command run against `origin/main` on 2026-08-23, re-run against `a4bb356` on 2026-08-30, and re-checked against `ebe77af` on 2026-08-31 — not read from a status document. Re-run these to re-verify.

Statements of *judgement* are not covered by that claim and are marked where they appear: the severity classes in §4.3, the reading that a defect is untested, and characterisations of review outcomes. Those rest on reading the artefacts, not on any command below.

| Claim | Command |
|---|---|
| Trunk tip and CI state | `git fetch origin && git log -1 origin/main`; `gh run list --branch main --limit 5` |
| Package statuses | parse `git show origin/main:docs/handoff/workstreams.yaml` |
| Task ledger state | parse `git show origin/main:specs/001-financial-evidence-lab/tasks.md` |
| Open work | `gh issue list --state open --limit 100`; `gh pr list --state open` |
| Release gates | `specs/001-financial-evidence-lab/spec.md` §19.5, §19.6, §26 |
| Credential state | `docs/handoff/CREDENTIALS.md` |
| Path contention | pairwise set-intersection of `allowed_paths` across unmerged packages |

**Where the handoff documents and this file disagree, this file's numbers were measured and the handoff documents' were not.** `STATUS.md` and `README.md` were reconciled by PR #172, merged 2026-08-31 @ `ebe77af`. `tasks.md` has not been reconciled at all (§4.2).

---

## 3. Verified state, 2026-08-31

- Trunk: `main` @ `ebe77af` (PR #172, the handoff reconciliation). Its parent `a4bb356` (PR #174, closing #171) remains the **measurement baseline** for every structural count below, and #172 is docs-only. All five GitHub Actions checks pass.
- Open PRs: **2** — #173 (this specification) and #175 (ADR-0011); both `MERGEABLE` / `CLEAN` with five of five checks passing.
- Open issues: **31**.

**Resolved since this document was first drafted** (2026-08-25 → 2026-08-31), each an item §8 listed as owed:

| Item | Outcome |
|---|---|
| #171 over-suppression regression | **Fixed and merged** — PR #174 @ `a4bb356`, red-green verified; issue closed |
| #146 terminal-run retry semantics | **Ruled** 2026-08-29 — Option 1, *terminal runs are final*; consumer drops or dead-letters a job whose run row is terminal. Issue stays open pending implementation |
| ADR-0009 vs #157 fork | **Ruled** — ADR-0011 accepted on PR #175; ADR-0009 marked `Superseded by ADR-0011`. #157 remains the implementing work |
| #134 Playwright E2E in CI | **Closed** — its work had already merged as PR #131 @ `bc6a2a3`, exactly as §8 item 7 recorded |
| #172 handoff reconciliation | **Merged** 2026-08-31 @ `ebe77af`. It flipped `EVALS-REPORT-RENDER` from `ready` to `merged`, and added `status: ready` to `M4-MODEL-CALC` — which **dispatches #63**, discharging §8 items 1 and 4 |

Structural measurements were **unchanged by #174**, which touched only `workers/src/fel_workers/extraction/validate/accounting.py` and `workers/tests/extraction/test_accounting_identities.py`. **#172 moved exactly one of them** — the `merged` package count — by flipping `EVALS-REPORT-RENDER`; it also added a `status:` key to `M4-MODEL-CALC` without changing any total. The rest hold: 32 packages, 21 ledger checkboxes, 2 `credentials:` keys, 5 "Not requested". Re-run and confirmed against `a4bb356` and `ebe77af`.
- Registered packages in `workstreams.yaml`: **32**
  - `status: merged` on trunk: **23** (**22** at the `a4bb356` baseline)
  - Effectively merged but stale in the queue: **0** — `EVALS-REPORT-RENDER` (#151) merged as PR #164 @ `a23514e` on 2026-08-11 but its entry read `ready` until PR #172 flipped it on 2026-08-31
  - **Genuinely outstanding: 9**
- Spec Kit tasks: **71 total**, **4 deferred post-MVP** (`T0211`, `T0212`, `T0213`, `T0506`) → **67 in scope**
  - Delivered: **38** — 39 tasks sit inside packages marked `merged`, but `T0112` is carved out because issue #56 was reopened for it (§4.2)
  - Outstanding: **29**

M0, M1 and M2 are code-complete. M3 core is merged. M3 review, M4 and M5 are entirely unbuilt.

---

## 4. What remains

### 4.1 Outstanding packages (9)

"Depth" = longest chain of unmerged dependencies terminating at this package.

| Package | Issue | Tasks | Depth | Dispatch state |
|---|---|---|---:|---|
| `M3-REVIEW` | #61 | T0308, T0309 | 1 | **All deps merged.** Held by two open rulings, not by dependencies |
| `M4-MODEL-CALC` | #63 | T0401–T0403, T0409, T0410 | 1 | **All deps merged; contends with nothing dispatchable.** Dispatched — carries `status: ready` on trunk since PR #172 |
| `READER-PROD-SMOKE` | #108 | — | 1 | All deps merged; **credential-gated** (`credentials: hosted-required`) |
| `M3-CONFIDENCE-GATE` | #62 | T0306, T0307, T0310 | 2 | `depends_on: [M3-REVIEW]` — edge confirmed real, §6.3 |
| `M4-FACT-SCENARIOS` | #64 | T0404, T0405 | 3 | `depends_on: [M4-MODEL-CALC, M3-CONFIDENCE-GATE]` |
| `M4-MODEL-UI` | #65 | T0406–T0408 | 4 | `depends_on: [M4-FACT-SCENARIOS]` |
| `M5-FORECASTING` | #66 | T0501–T0503, T0507 | 4 | `depends_on: [M4-FACT-SCENARIOS]` |
| `M5-BACKTEST` | #67 | T0504, T0505, T0508 | 5 | `depends_on: [M5-FORECASTING]` |
| `M5-AUDIT-RELEASE` | #68 | T0509–T0511, T0214b, T0512, T0513 | 6 | `depends_on: [M5-BACKTEST]` — **the release artifact** |

Plus **two packages this spec proposes registering**: `RELEASE-LIVE-CUTOVER` (§5.1), which `M5-AUDIT-RELEASE` must then depend on, and the migration-`0006` entry **ADR-0011 requires** for #157 (§4.4), which `M3-REVIEW`'s SSE surface waits on.

**Critical path, 6 deep:**
`M3-REVIEW (#61) → M3-CONFIDENCE-GATE (#62) → M4-FACT-SCENARIOS (#64) → M5-FORECASTING (#66) → M5-BACKTEST (#67) → M5-AUDIT-RELEASE (#68)`

### 4.2 Ledger drift — the canonical ledger under-reports by 17 tasks

`workstreams.yaml` names `specs/001-financial-evidence-lab/tasks.md` as `canonical_tasks`. It reports **21 of 67** in-scope tasks checked. Measured against merged packages, **38 of 67** are delivered by a package marked `merged`. Seventeen tasks are delivered on trunk and still read `[ ]`:

| Tasks | Owning package | Landed |
|---|---|---|
| `T0201`–`T0206` | `M2-RETRIEVAL-BACKEND` (#57) | PRs #114 + #119 @ `c546ec2` |
| `T0207`–`T0209`, `T0214a`, `T0215` | `M2-CLAIMS-VERIFICATION` (#58) | PR #122 |
| `T0210` | `M2-OBSERVATORY-UI` (#59) | PR #123 |
| `T0301`–`T0305` | `M3-EXTRACTION-CORE` (#60) | PR #145 @ `61058e4` |

`T0112` also reads `[ ]` and is **the one correct unchecked entry among these eighteen**: `M1-CORPUS-QA` (#56) merged its test suites (`T0111`), but #56 was reopened and remains open for the live 20-issuer ingest and corpus-quality metrics.

**Why this matters.** The canonical ledger is what an external agent reads to decide what is unbuilt. At 21/67 it implies M2 and M3-core are unstarted. An agent acting on it would redo merged work — the same failure mode as the stale `EVALS-REPORT-RENDER: ready` entry, which was wrong for the twenty days between PR #164's merge on 2026-08-11 and PR #172's correction on 2026-08-31, and would have caused an agent to re-take finished work throughout.

**Caveat on the reconciliation.** Checking a box asserts the parent spec's completion standard: "code, tests, telemetry, documentation, and acceptance evidence are present." Merge is strong evidence but not identical to that standard. `T0215` in particular (reference-corpus retrieval performance suite) should be confirmed against `packages/retrieval/ACCEPTANCE.md` before its box is checked, not inferred from #58's merge alone.

### 4.3 Release-blocking backlog (14 issues)

Per the scope decision recorded in `clarify-analyse.md` **Q-1**, **every open non-epic backlog issue is a release blocker.** This is the widest of the three scopes considered; §9 records the cost.

| Issue | Class | Feeds |
|---|---|---|
| #158 | Correctness | §19.6 temporal validity 100%; extraction identity integrity |
| #157 | Contract | **Gates #61's SSE surface.** The fork is ruled — ADR-0011 accepted, ADR-0009 superseded — so #157 is now the sanctioned implementation, not one branch of a choice. It is **not backlog only**: ADR-0011 requires it to be registered as its own `workstreams.yaml` package, sequenced before wave 1 (§4.4) |
| #154 | Correctness | §19.6 guidance F1 ≥ 90.0% |
| #153 | Correctness | §19.6 numeric accuracy |
| #146 | Design ruling | **Gates #61.** Ruled 2026-08-29 (Option 1, terminal runs final); open pending implementation |
| #143 | CI hygiene | Fail-closed `audit-bulk` gate reddens docs-only PRs |
| #141 | Process | Shared-path authorization. **Gates this PR** |
| #138 | Telemetry | Parent §18.1 |
| #137 | Cutover hygiene | Folds into `RELEASE-LIVE-CUTOVER`, §5 |
| #136 | Accessibility | Parent §16.3; consumed by `T0511` |
| #135 | Feature residue | Live SSE proxy deferred from #59; overlaps #61's surface |
| #133 | Test validity | Numeric identity tautology behind the accuracy gate |
| #132 | Exit gate | **M2's exit criterion (M2-024) is not met**; see §5 |
| #81 | Benchmark | §19.5 category coverage. The "≥ 8 distinct stress features" bar is #81's own wording, not §19.5's — §19.5 requires ten categories with ≥ 30 cases each |

Five milestone epics (#4–#8) and two reader trackers (#87, #96) close by rollup and are not separately actionable.

### 4.4 The second required registration — ADR-0011's migration-`0006` entry

`RELEASE-LIVE-CUTOVER` (§5.1) is **not** the only package this spec must count. **ADR-0011 (Accepted 2026-08-30 on PR #175) requires a second new `workstreams.yaml` entry** for the migration-`0006` work tracked by #157. Its Consequences say so outright: *"A new `workstreams.yaml` entry is required."* Until this spec counted it, #157 appeared in §4.3 as backlog only — owned by no package, placed in no wave. That was the gap.

**Paths, and what they contend with.** Per ADR-0011 the entry needs `db/migrations/**`, `db/migrations/tests/**`, `packages/contracts/**`, `specs/003-agentic-extraction/**` and `docs/decisions/**`, plus the `workers/src/fel_workers/extraction/**` and `workers/tests/**` paths currently held by `M3-EXTRACTION-CORE`. **Those last two are exactly the paths `M3-CONFIDENCE-GATE` (#62) claims**, so the two cannot run concurrently — ADR-0011 states this itself: *"That path overlap needs the integration lead to sequence it against #62."* `workers/tests/**` is additionally claimed by #66 and #67, and contained in the `workers/**` claimed by #108. Placing this entry before wave 1 avoids all four, since the earliest of them (#62) is wave 2.

**Scope of the block on #61 — SSE only.** ADR-0011's header is explicit: *"Blocks: #61 SSE until the **implementing** PR for migration 0006 lands. Non-SSE #61 work still waits on unimplemented #146 Option 1 (terminal runs final), which is a separate ruling."* Its first revisit trigger — *"#61 becomes ready to ship before the implementing PR lands"* — is **mandatory, not advisory**, but its remedy is to withhold the SSE surface rather than to hold all of #61. §6.2 therefore keeps #61 in wave 1 with its dispatch scoped **non-SSE**, which is the constraint §7 already records for that package.

> **A tension inside ADR-0011, disclosed rather than resolved.** Its Consequences also say *"Add this work to #61's `depends_on`"*, which read literally makes this entry a package-level predecessor of #61 — deepening the critical path from **6 to 7** and removing #61 from wave 1 entirely. This spec takes the narrower reading because it is the one ADR-0011's own header states, and because the depth figures throughout this document are measured against the registered graph, which carries no such edge today. **If the integration lead adds the `depends_on` edge instead, the critical path becomes 7, wave 1 holds #63 alone, and §4.1's Depth column shifts by one from `M3-REVIEW` downward.** That is a ruling for the lead, not an inference this spec should make.

---

## 5. The unowned workstream: mock → live cutover

**This is the largest gap and it is not in the queue.**

Verified:

1. `workstreams.yaml:73` sets `defaults.credentials: mock-only`.
2. Exactly one package overrides it — `READER-PROD-SMOKE` (#108), line 255, `credentials: hosted-required`. Every other package, **including `M5-AUDIT-RELEASE` (#68), inherits mock-only.**
3. `CREDENTIALS.md` lists five credential groups. **All five read "Not requested"**: Supabase URL + public key, Supabase service-role key, OpenAI API key, Alpha Vantage API key, Sentry DSN.
4. #68 owns `T0214b` — parent §19.5's frozen, dual-adjudicated benchmark of "at least 300 adjudicated questions across at least 20 US-listed B2B SaaS issuers" — and `T0513`, the immutable release artifact and signed evaluation report.
5. Parent §26 item 2 requires ingesting and inspecting "at least eight quarters of SEC filings and XBRL facts".

*(Neither quotation contains the word "real"; that these must be genuine filings rather than mocks is an inference from §19.5's adjudication requirement and §26's end-to-end framing, not a phrase either section uses.)*

A mock-only package cannot produce a dual-adjudicated benchmark over real issuers, nor evaluate ten numeric gates against it. **The dependency graph terminates at a package whose inherited credential setting does not provide what its acceptance criteria require.** (`credentials:` is a provisioning descriptor, not a prohibition — `workstreams.yaml`'s own comment on #108 reads "names only until lead provisions". Nothing in the file forbids anything; the gap is that nothing supplies it either.)

This is a class of defect the schema cannot express: `depends_on` orders packages against each other, but there is no vocabulary for "this package depends on something outside the repository existing." The graph therefore reports itself complete and internally consistent while pointing at an unreachable terminal node.

### 5.1 Resolution — register `RELEASE-LIVE-CUTOVER`

Per `clarify-analyse.md` **Q-2**, register a new package that owns the provisioning and live-evaluation surface, and add the edge into #68.

```yaml
  - id: RELEASE-LIVE-CUTOVER
    issue: <new>
    tasks: [T0112]           # MUST be deallocated from M1-CORPUS-QA in the same edit
    depends_on: [M2-CLAIMS-VERIFICATION, M3-EXTRACTION-CORE]
    team: trust
    branch: agent/release-live-cutover
    status: blocked          # opens when the lead provisions credentials
    credentials: hosted-required   # overrides defaults.credentials mock-only
    allowed_paths:
      - evals/**
      - workers/tests/**
      - docs/handoff/CREDENTIALS.md
```

`M5-AUDIT-RELEASE` then becomes `depends_on: [M5-BACKTEST, RELEASE-LIVE-CUTOVER]`.

**`T0112` must be deallocated in the same edit.** `M1-CORPUS-QA` (#56) currently declares `tasks: [T0111, T0112]`. Adding `T0112` to the new package without removing it there would make it the only task in the entire file owned by two packages, leaving §4.2's reconciliation ambiguous about who closes it. The registration edit is therefore two hunks, not one:

```yaml
  - id: M1-CORPUS-QA
    tasks: [T0111]           # was [T0111, T0112]; T0112 moves to RELEASE-LIVE-CUTOVER
```

**`issue:` must be a real number before the block lands.** Every other `issue:` in the file is an integer; `<new>` is a valid YAML string but would make this the one entry a typed consumer cannot read. File the issue first and inline its number.

**Path contention warning.** `evals/**` is already claimed by #62, #67, #68 **and #108**, and `workers/tests/**` by #62, #66, #67 **and #108** — the last of these by containment, since #108 claims the enclosing `workers/**` rather than the literal glob, which the exact-string method in §6.1 does not catch. This package therefore cannot run concurrently with any of them, which is why §6.2 places it in its own wave. Registering it is a `workstreams.yaml` edit and so is itself a shared-path change requiring `contract-change` + authorization per #141.

### 5.2 Decisions this package must resolve

- **Embeddings provider, selected by benchmark rather than preference.** #132 records that Anthropic ships no embeddings endpoint, so index build and query embedding cannot use Claude, even though generation and verification are directed to `claude-opus-4-8` under the replace-OpenAI directive. #132 marks this as blocking everything else within it. **This directive has no ADR.** ADR-0002 (Accepted) states "OpenAI for generation" and `text-embedding-3` embeddings; constitution principle V requires benchmark evidence and an approved ADR for any AI-provider substitution. See `clarify-analyse.md` finding **A-1** — a superseding ADR must land before this package can select a provider without violating the constitution.
- **Alpha Vantage budget authorization** — *not* a tier decision. ADR-0002 (Accepted) already rules that "the paid tier (≥ USD 49.99/month) is required," giving the free tier's 25 requests/day and premium-only adjusted series as the reason. `CREDENTIALS.md` goes further than restating it: it presents "a paid tier ... **or** an ADR revisiting the market-data adapter choice" as a live either/or, which is an escape hatch ADR-0002 already closed. Under ADR-0002's own change rule, that second branch requires benchmark evidence that the current default fails a requirement — it is not a free alternative. What is outstanding is provisioning and budget sign-off. See finding **A-6**.
- **Hosted Supabase and deployment secrets** for #108.
- **Adjudicator staffing and budget** — parent §19.5 requires two qualified reviewers to adjudicate disagreements across ≥ 300 questions.

Until this package exists, "how much is left" cannot be answered honestly, because the terminal step has no owner.

---

## 6. Dispatch sequence

### 6.1 Concurrency

`docs/handoff/README.md` forbids scheduling two packages with overlapping `allowed_paths` concurrently; overlap is resolved by time, not ownership.

Three outstanding packages have every dependency merged. Measured pairwise overlap:

| Pair | Result |
|---|---|
| `M3-REVIEW` (#61) ∥ `M4-MODEL-CALC` (#63) | **disjoint** |
| `M4-MODEL-CALC` (#63) ∥ `READER-PROD-SMOKE` (#108) | **disjoint** |
| `M3-REVIEW` (#61) ∥ `READER-PROD-SMOKE` (#108) | contends on `apps/web/**`, `apps/api/**` |

**`M4-MODEL-CALC` (#63) contends with nothing currently dispatchable.** Its sole path, `packages/calculation-engine/**`, is claimed by exactly one other *unmerged* package — #64, which depends on it. (M0-SCAFFOLD claims `packages/**`, which contains it, but is merged and so cannot contend. That containment is invisible to exact-string comparison — the very blindness the caveat below describes.) The only exclusion among the three is #61 vs #108.

Downstream contention is heavy: #62/#67/#68 all claim `evals/**`; #65/#66 both claim `apps/web/**` and `packages/ui/**`; #66/#67 both claim `workers/src/fel_workers/forecasting/**`; #61/#64/#68 all claim `apps/api/**`. *(This sentence is scoped to the downstream packages; #108 is not downstream and is treated in §5.1 and §6.2, where it does contend on `evals/**` and — by containment — `workers/tests/**`.)*

**Neither package awaiting registration is in the table above, and both add contention.** `RELEASE-LIVE-CUTOVER` claims `evals/**` and `workers/tests/**` (§5.1); ADR-0011's migration-`0006` entry claims `workers/src/fel_workers/extraction/**` and `workers/tests/**`, both held in full by #62 (§4.4). Sequencing the latter before wave 1 keeps it clear of #62, #66, #67 and #108 alike.

> **Method caveat.** These are exact-string comparisons of `allowed_paths` globs. They do not detect subtree containment — `evals/reporting/**` is a subtree of `evals/**` but compares as distinct. `workstreams.yaml` flags precisely this case for `EVALS-REPORT-RENDER`. Verify containment by hand before dispatching a narrowed path against a broad one.

### 6.2 Wave order

| Wave | Dispatch | Precondition |
|---|---|---|
| **0** | ~~fix #171~~ ✅ merged @ `a4bb356`; ~~rule #146~~ ✅ Option 1; ~~rule ADR-0009/#157~~ ✅ ADR-0011 accepted; ~~re-scope #134~~ ✅ closed; ~~merge #172~~ ✅ merged @ `ebe77af`, which also dispatched #63. **Remaining:** merge #173, #175; reconcile `tasks.md`; register `RELEASE-LIVE-CUTOVER`; **register and land ADR-0011's migration-`0006` entry for #157** (§4.4); land the ADR for **A-1**; resolve #141 and #143; implement the #146 ruling | None — integration-lead actions across several PRs. **The wave-1 gate (#171) has cleared** |
| **1** | #61 ∥ #63 | Both rulings are made. #61 needs #146's Option 1 *implemented*, and its dispatch is **non-SSE only** until #157's migration `0006` lands (§4.4); #63 needs nothing and already reads `status: ready` |
| **2** | #62 | #61 merged |
| **3** | #64 | #62 and #63 merged |
| **4** | #65, #66 — **contended** on `apps/web/**` and `packages/ui/**`; serialize | #64 merged |
| **5** | #67 | #66 merged |
| **6** | `RELEASE-LIVE-CUTOVER`, **then** #108 — contended, serialize | Credentials provisioned; `evals/**` free |
| **7** | #68 | #67 and `RELEASE-LIVE-CUTOVER` merged |

Within wave 6, `RELEASE-LIVE-CUTOVER` and #108 must serialize: the former claims `evals/**` and `workers/tests/**`, the latter claims `evals/**` and `workers/**`, which contains `workers/tests/**`. Waves 6 and 7 are separate because `RELEASE-LIVE-CUTOVER` and #68 both claim `evals/**`.

### 6.3 The #62 → #61 edge — ruled real, kept

`M3-CONFIDENCE-GATE` (#62) declares `depends_on: [M3-REVIEW]`, yet the two packages have **zero path overlap** (#62 owns `workers/src/fel_workers/extraction/**`, `workers/tests/**`, `evals/**`; #61 owns `apps/web/**`, `apps/api/**`). The edge is therefore logical rather than contention-driven, and breaking it would shorten the critical path from 6 to 5 and allow #62 to run parallel to #61.

**Ruling (`clarify-analyse.md` Q-3): the edge is real and stays.** #62 enforces the review thresholds that #61 implements; #62's acceptance requires exhaustive no-auto-approval tests over a review workflow that must exist first. The critical path remains 6 deep. Recorded here so the question is not silently re-opened by a later reader who notices the disjoint paths.

---

## 7. Per-package exit criteria

Every package inherits `defaults.required_evidence: [tests, telemetry-if-applicable, documentation, acceptance-notes]`. Package-specific gates, traced to the parent spec and issue bodies:

- **#61 `M3-REVIEW`** — accept/edit/reject/merge/rerun workflows (`FR-EXT-003`); versioned approved records with correction history. Must not expose the SSE surface until #157 is **implemented** — migration `0006`, per ADR-0011. The fork itself is ruled (§8 item 2), so what remains is the work, not the decision.
- **#63 `M4-MODEL-CALC`** — node types; dependency edges, cycle detection, versioned graph snapshots (`FR-MOD-001`); server-side decimal engine with typed units (`FR-MOD-002`); property tests for decimal arithmetic, units, periods, cycles and scenario immutability; **5,000-node p95 recalculation target** (`T0410`).
- **#62 `M3-CONFIDENCE-GATE`** (criteria below from #62's issue body, not the parent spec) — deterministic `isotonic-v1` calibration recording dataset/ontology/workflow/prompt/model/version hashes, breakpoints, counts, ECE and Brier; 0.85 record / 0.80 field thresholds; exhaustive no-auto-approval tests for monetary facts, guidance and assumptions; insufficient data yields confidence 0 and high priority; owner-only, bounded, versioned, audited threshold changes. Contradiction detection stays M2-owned — reference its report, add no detector.
- **#64 `M4-FACT-SCENARIOS`** — approved extractions to source-backed model nodes (`FR-EXT-004`); sparse bull/base/bear layers (`FR-MOD-003`).
- **#65 `M4-MODEL-UI`** — interactive driver graph; price-volume-mix bridges, waterfalls, heatmaps, tornado charts; formula, dependency, assumption, citation, diff and restore views (`MOD-002`, `MOD-004`).
- **#66 `M5-FORECASTING`** — common fit/predict/backtest interface and immutable forecast-run contract (`FR-FOR-001`, `FR-FOR-002`); last-value and seasonal-naive quarterly baselines; analyst driver forecasts for revenue, ARR where disclosed, and gross profit.
- **#67 `M5-BACKTEST`** — rolling-origin backtests over one-to-eight-quarter horizons; 50%, 80% and 95% intervals with calibration metrics; advanced models stay non-default unless they beat the seasonal-naive median-MAE gate, which parent §19.6 scopes to **the supported one-to-four-quarter horizon** — a narrower window than the backtests themselves span.
- **`RELEASE-LIVE-CUTOVER`** — credentials provisioned and recorded in `CREDENTIALS.md`; embeddings provider selected by benchmark; `T0112` twenty benchmark issuers ingested with corpus-quality metrics; #132 live 65-question M2 exit gate passed; #81 stress cohort restored; #137 hygiene items closed.
- **#68 `M5-AUDIT-RELEASE`** — complete source-to-export audit traversal; Markdown/PDF briefs, CSV/XLSX tables, JSON evidence bundles and workspace manifests; accessibility, security, load, restore, provider-failure and browser suites; the frozen benchmark (`T0214b`); verification of every §19.6 gate and §26 item (`T0512`); the immutable release artifact and signed evaluation report (`T0513`). **`FOR-004`** — exports distinguish reported, modeled and user-supplied values — is unowned by any task and belongs here (**A-11**).

---

## 8. Still owed by the integration lead

Four decisions were resolved in `clarify-analyse.md` (Q-1 through Q-4). These remain:

1. ~~**Merge PR #172**~~ — **merged** 2026-08-31 @ `ebe77af`. Beyond reconciling `STATUS.md`, `README.md` and `workstreams.yaml`, it **dispatched #63**: the `M4-MODEL-CALC` entry now carries `status: ready`, where before it had no `status:` key and inherited `defaults.status: blocked`. It also flipped `EVALS-REPORT-RENDER` to `merged`, closing the stale-`ready` window §4.2 and §9 describe. This discharges item 4 below.
2. ~~**ADR-0009 vs #157**~~ — **ruled.** ADR-0011 accepted on PR #175; ADR-0009 `Superseded by ADR-0011`. #61's SSE surface now waits on #157 being *implemented* (migration `0006`), not on a decision.
3. ~~**#146**~~ — **ruled** 2026-08-29: Option 1, terminal runs are final. Still a producer gate for #61 until implemented; the issue remains open for that reason.
4. ~~**Dispatch #63**~~ — **done by item 1.** PR #172 added the `status: ready` key; #63 had zero contention and was independent of items 2 and 3.
5. **Register `RELEASE-LIVE-CUTOVER`** and file its issue (§5.1), then answer its four questions (§5.2). **Separately, register ADR-0011's migration-`0006` entry for #157** and sequence it before wave 1 (§4.4) — these are two distinct registrations, not one.
6. **Reconcile `tasks.md`** — 17 checkboxes, with the `T0215` caveat in §4.2. While there, **cite `FOR-004` on `T0510`**: of the 53 parent-spec requirement IDs, **fourteen are referenced by no task**, but `FOR-004` is the only one that is *also* uncovered by any task's prose — and it carries constitution principle II's provenance guarantee into exports (finding **A-11**).
7. ~~**Re-scope or close #134**~~ — **closed** 2026-08-29; its work had merged as PR #131 @ `bc6a2a3`.
8. **Ratify this spec**, or return it with scope changes.

---

## 9. Risks

| Risk | Evidence | Mitigation |
|---|---|---|
| Release gates unevaluable in mock mode | §5; `CREDENTIALS.md` all-"Not requested"; `workstreams.yaml:73` | Register `RELEASE-LIVE-CUTOVER` now, not at wave 6 |
| Canonical ledger under-reports by 17 tasks | §4.2, measured | Reconcile now — #172 has merged, so nothing blocks it; confirm `T0215` against `packages/retrieval/ACCEPTANCE.md` |
| Stale `status:` re-dispatches finished work | `EVALS-REPORT-RENDER` read `ready` for the twenty days from PR #164's merge on 2026-08-11 until PR #172 corrected it on 2026-08-31 | Confirm the issue is open on GitHub before trusting `ready` |
| Green CI is not a correctness claim | #171 was live on `5b4b77c` with all five checks passing, because no test covered it. **Fixed by PR #174**, which added the missing coverage | The principle stands even though this instance is closed: read gate-green as "nothing we check is broken". A live example remains — the whole 1009-test Python suite passes with the `_check_segment_sums` suppression mechanism deleted outright, so its lower bound is still untested |
| Six-deep critical path, one uncontended package | §6.1, measured | #63 is now dispatched (`status: ready` via #172); it blocks nothing and is blocked by nothing |
| M2 exit criterion not actually met | #132 open; PR #122 merged mock plumbing only | Folded into `RELEASE-LIVE-CUTOVER`; do not treat M2 as closed |
| Alpha Vantage paid tier is an accepted-ADR obligation, unbudgeted | ADR-0002 (Accepted) requires ≥ USD 49.99/mo; `CREDENTIALS.md` reads "Not requested" | Budget sign-off, or a new ADR reversing ADR-0002 |
| **Replace-OpenAI directive contradicts ADR-0002 with no superseding ADR** | #132 directs `claude-opus-4-8`; ADR-0002 (Accepted) says OpenAI; constitution V requires an ADR + benchmark | Land the superseding ADR before `RELEASE-LIVE-CUTOVER` selects a provider (finding A-1) |
| **Zero-open-backlog scope adds four non-gated blockers** | #135, #137, #138, #143 are required by no §19.6 gate and no T-task | Deliberate choice (Q-1). Revisit if schedule pressure appears; dropping them costs no gate |
| **ADR-0011 mandates a second registration that no wave owned** | ADR-0011 Consequences: "A new `workstreams.yaml` entry is required"; #157 sat in §4.3 as backlog only | Register it and sequence before wave 1 (§4.4); scope #61's wave-1 dispatch non-SSE until migration `0006` lands |
| Registering a new package is itself a shared-path change | `workstreams.yaml` is in `shared_paths` | `contract-change` + authorization record per #141, and this now applies **twice** — once per registration |

---

## 10. Summary

| Measure | Value |
|---|---|
| Packages outstanding | 9 registered + 2 to register = **11** — `RELEASE-LIVE-CUTOVER` (§5.1) and ADR-0011's migration-`0006` entry (§4.4) |
| Spec Kit tasks outstanding | **29 of 67** in scope |
| Critical path depth | **6** (edge #62→#61 ruled real and kept) |
| Packages with every dependency merged | **3** — #61, #63, #108 |
| Of those, dispatchable with no ruling and no credential | **1** — #63, which contends with nothing and was dispatched by #172 (`status: ready`) |
| Safe parallel pairs among the 3 dispatchable | 2 of 3 (#61∥#63, #63∥#108; #61 vs #108 contends) |
| Open issues | 31 — 14 release-blocking, 5 epics, 2 rollup trackers, **10 package issues (the 9 outstanding packages + #56)**. Not the same 10 as the row above: neither package awaiting registration has an issue yet, and #56 is not an outstanding package. Was 33; #171 and #134 closed 2026-08-29 |
| Release gates to satisfy | 10 numeric + 11 definition-of-done items |
| Ledger drift to correct | 17 checkboxes |
