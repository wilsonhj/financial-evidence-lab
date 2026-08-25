# MVP Completion — `/speckit.clarify` and `/speckit.analyse`

**Feature:** `specs/004-mvp-completion/`
**Date:** 2026-08-25
**Baseline:** `origin/main` @ `5b4b77c`

---

## Clarifications resolved with the integration lead

Four questions materially changed the artifacts. All four were put to the integration lead and answered; none was resolved by assumption.

| ID | Question | Resolution |
|---|---|---|
| **Q-1** | What counts as "complete" for `T0513`? | **Zero open backlog.** All 16 open non-epic issues close before release — not only those a §19.6 gate or a T-task requires. This is the widest of the three scopes offered; #135, #137, #138 and #143 become release blockers despite no gate demanding them. Recorded as a risk in `spec.md` §9 so the choice stays visible |
| **Q-2** | How should the unowned live-data cutover be represented? | **Register a new `RELEASE-LIVE-CUTOVER` package** with a `credentials:` override, absorbing #132, #137, #56/`T0112` and #81, and make `M5-AUDIT-RELEASE` depend on it. Rejected: widening #68's scope in place, which leaves provisioning invisible until wave 6 |
| **Q-3** | Is `M3-CONFIDENCE-GATE`'s dependency on `M3-REVIEW` real, given zero path overlap? | **Real; the edge stays.** #62 enforces the review thresholds #61 implements, and its no-auto-approval tests require a review workflow to exist. Critical path remains 6 deep. Rejected: breaking the edge for a 6→5 shortening, which would have let #62 run parallel to #61 |
| **Q-4** | What should this feature directory contain, given the constitution names `001/` as sole canonical? | **`spec.md` + `plan.md` + `clarify-analyse.md`; no `tasks.md`.** The outstanding work already carries canonical IDs in `001/tasks.md`, and a fourth ledger of the same rows would reproduce the drift documented in `spec.md` §4.2. `plan.md` lands with an explicit subordination header; the constitutional tension is recorded as **C-1** below for the lead to rule on |

---

## Analysis findings and disposition

Severity reflects consequence if unaddressed, not effort to fix.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| **A-1** | HIGH | The replace-OpenAI directive recorded in #132 substitutes `claude-opus-4-8` for ADR-0002's accepted "OpenAI for generation", with no superseding ADR and no benchmark evidence. Constitution principle V names additional AI providers explicitly and requires both | **Unresolved — needs a superseding ADR before `RELEASE-LIVE-CUTOVER` selects any provider.** Either choice violates something today: following the directive breaches ADR-0002, following ADR-0002 contradicts a standing directive. `plan.md` records this as a failed Constitution Check with a Complexity Tracking entry |
| **A-2** | HIGH | `M5-AUDIT-RELEASE` (#68) inherits `defaults.credentials: mock-only` yet owns `T0214b` (dual-adjudicated ≥300-question benchmark over ≥20 real issuers) and `T0513`. The dependency graph terminates at a package whose inherited credential policy forbids it from meeting its acceptance criteria | **Resolved in design by Q-2** — register `RELEASE-LIVE-CUTOVER` and add the edge. Not resolved in fact until the lead files the issue and provisions credentials. Root cause is schema-level: `depends_on` cannot express a precondition outside the repository |
| **A-3** | HIGH | The canonical ledger `001/tasks.md` reports 21 of 67 in-scope tasks complete; measured against merged packages the figure is 38. Seventeen delivered tasks still read `[ ]` | **Reconcile in a follow-up PR**, not this one — `001/tasks.md` is a shared path and a separate authorization. `spec.md` §4.2 lists the exact 17 and flags that `T0215` should be confirmed against `packages/retrieval/ACCEPTANCE.md` rather than inferred from #58's merge |
| **A-4** | HIGH | Constitution principle IV (secrets via approved flows) cannot be asserted: all five credential groups in `CREDENTIALS.md` read "Not requested", so the flow has never been exercised | **Assigned to `RELEASE-LIVE-CUTOVER`.** Recorded as a failed Constitution Check in `plan.md` with a Complexity Tracking justification |
| **A-5** | MEDIUM | M2's exit criterion M2-024 is not met — #132 is open and PR #122 merged mock-first plumbing only — yet M2 is described as complete in the handoff documents | **Folded into `RELEASE-LIVE-CUTOVER`.** `spec.md` §3 states M2 is *code*-complete rather than complete, and §4.3 lists #132 as release-blocking |
| **A-6** | MEDIUM | `CREDENTIALS.md` offers "a paid tier ... **or** an ADR revisiting the market-data adapter choice" as a live either/or. ADR-0002 (Accepted) already ruled the paid tier required, and its change rule admits a superseding ADR only on benchmark evidence that the current default fails a requirement. The handoff document therefore advertises an escape hatch the accepted ADR has closed | **Corrected in `spec.md` §5.2** — reframed from "unresolved product decision" to budget authorization against an accepted ADR, with the either/or contradiction named. `CREDENTIALS.md` itself should be amended to drop the second branch or cite the evidence ADR-0002 requires; that is a `docs/handoff/**` edit outside this PR's scope |
| **A-7** | MEDIUM | #134 tracks work that already merged: PR #131 @ `bc6a2a3` landed Playwright E2E in CI but declared no closing issue, so #134 never auto-closed and still reads as pending release-blocking work | **Re-scope or close #134.** Listed in `spec.md` §8. Under the Q-1 zero-backlog scope this stale issue would otherwise block release on work already done |
| **A-8** | MEDIUM | Trunk CI is green at `5b4b77c` while carrying the #171 over-suppression regression. All five checks pass because no test covers the defect | **Recorded, not fixed here.** `spec.md` §9 states green must be read as "nothing we check is broken". #171's fix is a Wave 0 item requiring a red-green regression test |
| **A-9** | MEDIUM | Path-contention analysis uses exact-string comparison of `allowed_paths` globs and cannot detect subtree containment — `evals/reporting/**` is a subtree of `evals/**` but compares as distinct | **Documented as a method caveat** in `spec.md` §6.1. `workstreams.yaml` already flags this exact case for `EVALS-REPORT-RENDER`. Containment must be checked by hand before dispatching a narrowed path against a broad one |
| **A-10** | LOW | Checking a ledger box asserts the parent's completion standard — "code, tests, telemetry, documentation, and acceptance evidence are present" — which merge alone does not establish | **Caveat recorded** in `spec.md` §4.2 against the A-3 reconciliation |
| **A-11** | MEDIUM | An independent requirements-coverage pass over all 53 parent-spec requirement IDs found **zero genuinely unowned requirements** — but exactly one, `FOR-004` ("Forecast exports distinguish reported, modeled, and user-supplied values"), is cited by no task in the canonical ledger. `T0510` enumerates export *formats* only. This is not mere citation hygiene: `FOR-004` is the export-side expression of constitution principle II, "Reported, derived, user-supplied, and forecast values MUST remain distinguishable" — the one constitutional guarantee with no task anchor | **Cite `FOR-004` on `T0510`** when `001/tasks.md` is reconciled under A-3, following the ledger's own convention (`T0309`→`EXT-004`, `T0408`→`MOD-002`, `004`). Ownership is unambiguous either way: `M5-AUDIT-RELEASE` (#68) holds `T0509`/`T0510` and `packages/export/**`. Nothing implements it today — `packages/export/**` does not exist on trunk |
| **C-1** | MEDIUM | The constitution states `specs/001-financial-evidence-lab/` holds the **sole canonical** `spec.md`, `plan.md` and `tasks.md`. This feature adds the repository's second `plan.md` | **Needs an integration-lead ruling.** Three options: (a) accept the subordination header in `plan.md` as sufficient, (b) amend the constitution under its Governance section to permit subordinate plans in milestone feature directories, (c) drop `plan.md` and follow the 002/003 precedent exactly. Note the clause is *already* strained: `002/` and `003/` each ship their own `spec.md` and `tasks.md`, so "sole canonical" has not held literally since 002 landed. This PR does not resolve the tension; it surfaces it |

---

**Result:** Q-1 through Q-4 are resolved and reflected in `spec.md` and `plan.md`. Of the analysis findings, A-6 was corrected in-place during drafting; A-3, A-5, A-7, A-8, A-9, A-10 and A-11 are recorded with named owners and follow-up routes; A-2 and A-4 are resolved in design and assigned to a package the lead must still register; **A-1 and C-1 require integration-lead rulings and are not resolved by this PR.** No finding is silently deferred.

**Template conformance:** `plan.md` carries every section `.specify/templates/plan-template.md` requires, in template order, with no `Option` labels remaining and a populated `Structure Decision`. It adds one section the template does not list — `## Phasing`, between Project Structure and Complexity Tracking — because this is a sequencing plan and wave order is its substance. Disclosed here rather than left silent. The template presents its own structure "in advisory capacity", so this is an addition, not a breach.

**Coverage result:** an independent pass over all 53 parent-spec requirement IDs found **no requirement without an owner**. Thirty-nine are cited explicitly once range and shorthand notation is expanded (`FR-WRK-001`–`004`, `FR-RAG-005`, `007`, `008`, and similar); fourteen are uncited but covered by task prose or by the child specifications `002/` and `003/`; `UX-ATL-001`–`005` are cited only by the struck-through deferred tasks `T0212`/`T0213`, consistent with parent §8.1. `FOR-004` is the sole weak point and is recorded as A-11.

---

## Constitution check

Mirrors `plan.md`, which is authoritative for the gate result.

- **Evidence and temporal integrity:** preserved unchanged. This feature adds no evidence path and no retrieval surface; the 100% temporal-validity gate remains a release blocker, and the sole outstanding ingestion work (`T0112`) routes through `RELEASE-LIVE-CUTOVER` under the already-merged M1 cutoff suites.
- **Deterministic financial computation:** untouched. `M4-MODEL-CALC` (#63) carries the decimal-engine and property-test obligations verbatim from `T0403`/`T0409`; nothing here relaxes or reinterprets them.
- **Test-first quality gates:** honoured in sequencing. Wave 0 places the #171 red-green regression test and the ledger reconciliation *before* any dispatch, so no package is built against a ledger that misreports its dependencies.
- **Security and cost boundaries:** **cannot be asserted (A-4).** The approved secret-management flow has never been exercised — all five credential groups read "Not requested". Re-check required before wave 6.
- **Simplicity and provider isolation:** **cannot be asserted (A-1).** The replace-OpenAI directive substitutes an AI provider against ADR-0002 (Accepted) with neither a superseding ADR nor benchmark evidence, both of which principle V requires.

**Gate result: FAILS, two of five.** Both failures are pre-existing repository conditions that this feature surfaces and assigns owners to, not complexity it introduces. Per the Governance section a failed mandatory gate blocks merge for *implementation* work; this is a planning artifact whose purpose is to give those failures owners.
