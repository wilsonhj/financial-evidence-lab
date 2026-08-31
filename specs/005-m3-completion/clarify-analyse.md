# M3 Completion — `/speckit.clarify` and `/speckit.analyse`

**Feature:** `specs/005-m3-completion/`
**Date:** 2026-08-31
**Baseline:** `origin/main` @ `ebe77af`

---

## Clarifications resolved with the integration lead

Four questions changed this specification's content. All four were put to the lead and answered; none was resolved by assumption.

| ID | Question | Resolution |
|---|---|---|
| **Q-1** | ADR-0011 contradicts itself: its header blocks only #61's SSE surface, its Consequences say "Add this work to #61's `depends_on`". Which governs? | **The header.** The `0006` work blocks the SSE surface only. #61 is dispatchable non-SSE; the critical path stays **6**, where the alternative would have made it 7 and emptied wave 1 of everything but #63. Recorded in `spec.md` §4.2 with the rejected reading named, so it is not silently re-opened |
| **Q-2** | Finding A-1 — #132 directs `claude-opus-4-8` against ADR-0002's accepted "OpenAI for generation", with principle V unsatisfied in both directions | **Draft ADR-0012 (Proposed)** superseding ADR-0002's provider clause only, split by role, and explicit that the benchmark evidence principle V requires does not yet exist. Rejected: filing an issue and deferring, which leaves `M3-304` with no lawful provider |
| **Q-3** | Finding C-1 — `004/plan.md` is the repository's second `plan.md`, which the constitution forbids | **One MINOR constitution amendment** (1.1.0 → 1.2.0), scoping the clause to the canonical *ledger* and permitting subordinate spec/plan artifacts. Retroactively legitimises `002/` and `003/`, which have been in breach since July. Rejected: a per-directory waiver, which leaves the next directory in the same position |
| **Q-4** | How far does the lead's "do all of the above" reach on repo-modifying actions? | **Merges, issues and specs proceed; the two package registrations land as a reviewable PR, unmerged.** Registering a package adds dispatch keys, which are the triggers agents act on — those do not go live without the lead |

---

## Analysis findings and disposition

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| **A-1** | HIGH | **M3 cannot complete in the repository's current configuration.** `M3-304` requires a live provider smoke with an approved secret; all five credential groups read "Not requested"; #62 inherits `defaults.credentials: mock-only` and carries no override | **Unresolved.** `spec.md` §5. Needs `RELEASE-LIVE-CUTOVER` registered, a `credentials:` override on #62, and either provisioning or an explicit ruling that `M3-304` is deferred |
| **A-2** | HIGH | The credential `M3-304` names is contested. `M3-304` says OpenAI; #132 says `claude-opus-4-8`; ADR-0002 (Accepted) says OpenAI; principle V requires an ADR **and** benchmark evidence, and neither exists | **ADR-0012 drafted (Proposed).** Until ruled, `M3-304` cannot execute against any provider without violating something |
| **A-3** | MEDIUM | **`specs/004-mvp-completion/` §5 locates this gap one milestone too late.** It frames mock-only as blocking the *release* (`M5-AUDIT-RELEASE`, `T0214b`). The same defect blocks *M3* | **Recorded here.** 004's analysis is correct but its scoping understated the urgency; this document supersedes 004 on the timing of that gap, not on its substance |
| **A-4** | MEDIUM | `M3-303` evaluates 99% numeric accuracy against a validator with four open defects (#153, #154, #158, #133) | **Sequenced before `M3-303`** in `spec.md` §6 wave 0. #153 and #154 move persisted identity keys and need an ADR first |
| **A-5** | MEDIUM | The `0006` entry and #62 claim the same two path globs, so they can never run concurrently — but nothing in the queue records this, because neither entry exists yet | **Modelled** in `spec.md` §4.3 and §6.1; the contention note is written into the registration PR's entry comment |
| **A-6** | MEDIUM | #146 is **ruled but unimplemented**, and remains a producer gate on #61. An issue that is ruled reads as closed to a scanner | **Recorded** in `spec.md` §4.1 and §8 item 6. The issue is correctly still open |
| **A-7** | LOW | `T0301`–`T0305` are delivered but read `[ ]` in the canonical ledger, so M3-core scans as unstarted | Part of the 17-checkbox reconciliation; filed separately |
| **A-8** | LOW | This directory could have duplicated 003's milestone task IDs into a local `tasks.md` | **Declined.** 003 already carries `M3-200`–`M3-304`; a second copy is the drift constitution v1.2.0 exists to prevent |

---

**Result:** Q-1 through Q-4 are resolved and reflected in `spec.md` and `plan.md`. A-4 through A-8 are recorded with owners and routes. **A-1 and A-2 are unresolved and gate M3's completion, not merely its release** — they are the reason this document exists rather than being folded into `specs/004-mvp-completion/`.

---

## Constitution check

Mirrors `plan.md`, which is authoritative for the gate result.

- **Evidence and temporal integrity:** preserved. This document adds no evidence path; #61's cutoff validation (`M3-200`) and #62's calibration inputs are specified in 003 and unchanged here.
- **Deterministic financial computation:** untouched. M3 proposes; it does not compute authoritative financial values.
- **Test-first quality gates:** honoured. Wave 0 places the four correctness fixes and the #146 implementation before any dispatch, so #62 is not built to measure a validator with known defects.
- **Security and cost boundaries:** **cannot be asserted (A-1).** The approved secret-management flow has never been exercised, and `M3-304` requires it.
- **Simplicity and provider isolation:** **cannot be asserted (A-2).** The provider substitution has neither the ADR nor the benchmark evidence principle V requires; ADR-0012 is drafted to close it.

**Gate result: FAILS, two of five.** Both failures are pre-existing repository conditions this document surfaces and assigns owners to. The Governance clause is unqualified — *"a failed mandatory gate blocks merge"* — so merging this specification requires an integration-lead waiver recorded on its pull request, as `specs/004-mvp-completion/` also required.
