# Specifications

This folder holds the parent specification and the subordinate feature and
completion packages. Created under
[ADR-0032](../docs/decisions/ADR-0032-documentation-status-reconciliation.md)
(2026-10-31). It is a shared path: per `AGENTS.md` "Shared paths", changes need
the `contract-change` label, an accepted ADR and integration-lead review.

The canonical task ledger,
[`001-financial-evidence-lab/tasks.md`](001-financial-evidence-lab/tasks.md),
governs task state. It is the only file whose checkboxes are maintained. A
subordinate package's status line, milestone task list (`M2-*`, `M3-*`) or
measured snapshot is a record of when it was written; where it disagrees with
the ledger, the ledger wins. Each `spec.md` `Status:` line is authoritative for
that package's own standing; the table below abbreviates it.

| Spec | Parent | Status | Ratifying PR | Milestone / tasks covered |
|---|---|---|---|---|
| [001 financial evidence lab](001-financial-evidence-lab/spec.md) | — (canonical) | Canonical, v1.2 | Not recorded in this repository | All milestones M0–M5; every `T####` task |
| [002 observable hybrid retrieval](002-observable-hybrid-retrieval/spec.md) | 001 v1.2 | Implemented except `T0215` | PR #102 (2026-07-16) | M2: `T0201`–`T0210`, `T0214a`, `T0215` |
| [003 agentic extraction](003-agentic-extraction/spec.md) | 001 v1.2 | Partly implemented: `T0301`–`T0305` checked, `T0306`–`T0310` open | PR #102 (2026-07-16) | M3: `T0301`–`T0310` |
| [004 MVP completion](004-mvp-completion/spec.md) | 001 v1.2 | Ratified; §3 is a 2026-08-31 snapshot | PR #173 @ `fdcb3d2` (2026-08-31) | M3–M5 completion: `T0306`–`T0310`, `T0401`–`T0410`, `T0501`–`T0513` (less `T0506`), `T0214b`, `T0112` |
| [005 M3 completion](005-m3-completion/spec.md) | 001 v1.2; sequences 003 | Merged; scope still open in the ledger | PR #182 @ `4e91235` | M3 remainder: `T0306`–`T0310` |
