# Glossary

Terms that the specification, handoff ledgers, and ADRs use without
introduction. Each entry links to the source that governs it; when this page
and that source disagree, the source wins. Entries are alphabetical.

## Abstention

The outcome when evidence is missing: a claim, extraction run, or forecast lane
declines to answer instead of producing a plausible-looking result. Source:
[spec §14](../specs/001-financial-evidence-lab/spec.md) and
[M2 spec](../specs/002-observable-hybrid-retrieval/spec.md).

## ADR (architecture decision record)

A numbered, dated decision under [`docs/decisions/`](decisions/README.md) with a
status such as Proposed, Accepted, or Superseded. Shared contracts, migrations,
and `specs/**` change only with an accepted ADR. Source:
[`AGENTS.md`](../AGENTS.md#shared-paths).

## allowed_paths

The list of files or globs a work package may edit, recorded on its entry in
[`workstreams.yaml`](handoff/workstreams.yaml). An agent stays inside its
issue's `allowed_paths`, and two active packages must not overlap. Source:
[`AGENTS.md`](../AGENTS.md#working-rules).

## BYOK (bring your own key)

User-funded inference where each user supplies their own provider credential;
there is no owner-key fallback. Source:
[ADR-0026](decisions/ADR-0026-public-workspaces-and-user-funded-inference.md).

## Citation and citation integrity

A citation is an edge from a claim to a stable [source span](#source-span),
graded `entailed`, `partial`, `contradictory`, or `irrelevant`. Citation
integrity means every citation resolves to the exact hashed evidence it
claims, enforced by code and tests rather than model judgment. Sources:
[spec §11.3](../specs/001-financial-evidence-lab/spec.md#113-claim-and-citation-states),
[`AGENTS.md`](../AGENTS.md#working-rules).

## Claim

An atomic assertion in an answer, with the closed status set `supported`,
`partially_supported`, `contradicted`, `derived`, or `unsupported`. Only
`supported` and `derived` claims may be shown as factual conclusions. Source:
[spec §11.3](../specs/001-financial-evidence-lab/spec.md#113-claim-and-citation-states).

## contract-change

The GitHub label required on every pull request that edits a
[shared path](#shared-paths). Depending on the class of change it also needs an
accepted ADR or an integration-lead authorization record. Source:
[`AGENTS.md`](../AGENTS.md#shared-paths).

## Deployment mode

The operator-selected `FEL_DEPLOYMENT_MODE` (`fixture`, `reader-smoke`,
`synthetic-http`, or public when unset). Public mode refuses business web routes
with HTTP 503 rather than using a shared deployment identity. Source:
[ADR-0027](decisions/ADR-0027-deployment-modes.md).

## Evidence

Source material and everything derived from it with provenance: immutable
documents and versions, sections, passages, tables, normalized facts, and
source spans. Evidence is versioned, never silently rewritten. Sources:
[spec §11.1](../specs/001-financial-evidence-lab/spec.md#111-core-entities),
[architecture overview](architecture/overview.md).

## Fable

The scheduler and recovery coordinator for parallel agents. It assigns one
package per worktree, polls PRs, and records blockers in GitHub; it does not
make architecture decisions or merge code. Source:
[`FABLE_ORCHESTRATION.md`](handoff/FABLE_ORCHESTRATION.md).

## Fixture mode

Running the web app against deterministic committed fixtures with
`FEL_DEPLOYMENT_MODE=fixture` and `FEL_EVIDENCE_SOURCE=fixture`, with no API,
database, or provider. It is explicit and must never be a silent fallback in a
deployed environment. Source: [local development](development/local.md).

## Integration lead

The owner of shared paths and the only role that changes package status to
`merged`, checks tasks in the canonical ledger, changes dependencies, or
updates shared contracts. `workstreams.yaml` names the current lead. Sources:
[handoff README](handoff/README.md#source-of-truth),
[`AGENTS.md`](../AGENTS.md#shared-paths).

## Ledger

Either the **canonical task ledger**,
[`specs/001-financial-evidence-lab/tasks.md`](../specs/001-financial-evidence-lab/tasks.md)
(the sole record of `T####` completion), or the **handoff ledgers**,
[`workstreams.yaml`](handoff/workstreams.yaml) and
[`STATUS.md`](handoff/STATUS.md), which record package state and dated
evidence. Ledger prose follows the rules in the
[handoff README](handoff/README.md#reviewing-ledger-changes). Source:
[`AGENTS.md`](../AGENTS.md#read-before-changing-code).

## Milestones (M0–M5)

The six delivery increments of the canonical plan, each with an objective exit
gate:

| Code | Name |
|---|---|
| M0 | Platform and contracts |
| M1 | Point-in-time evidence corpus |
| M2 | Observable hybrid retrieval |
| M3 | Agentic extraction |
| M4 | Revenue and gross-profit model |
| M5 | Forecast Lab and MVP release |

Source: [plan §3](../specs/001-financial-evidence-lab/plan.md#3-milestones).

## Mock-first

Building and testing against committed mocks and fixtures before any live
provider is wired, with credentials requested only when a scoped live test is
ready. Sources: [`AGENTS.md`](../AGENTS.md#working-rules),
[handoff README](handoff/README.md#current-state).

## Point-in-time / temporal cutoff

A query with cutoff `T` may retrieve only evidence whose public-availability
timestamp is at or before `T`; backtests use the same rule. Workspaces and
queries carry this as-of cutoff. Source:
[spec §10.3](../specs/001-financial-evidence-lab/spec.md#103-point-in-time-correctness).

## RRF (reciprocal-rank fusion)

The deterministic method that merges the dense, lexical, fact, and table
retrieval lanes into one ranking (k = 60). Source:
[system design](architecture/system-design.md#query-execution).

## Search Observatory

The web view at `/observatory` that shows each retrieval lane, fusion, and
rejected candidates for a query, and replays saved traces. Source:
[spec §8.2](../specs/001-financial-evidence-lab/spec.md#82-search-observatory).

## Shared paths

Repository paths owned by the integration lead (for example `.github/`,
`.specify/`, `specs/`, `packages/contracts/`, `db/migrations/`,
`docs/decisions/`, the handoff ledgers, and root package/lock/config files).
Editing one requires the `contract-change` process. The full list is in
[`AGENTS.md`](../AGENTS.md#shared-paths) and the `shared_paths` key of
[`workstreams.yaml`](handoff/workstreams.yaml).

## Source span

A stable pointer into a document version (section, page, character offsets,
and text hash) that citations reference instead of copied text. Source:
[spec §11.2](../specs/001-financial-evidence-lab/spec.md#112-source-spans).

## Spec Kit

The specification-driven workflow this repository uses: a constitution in
`.specify/memory/`, templates in `.specify/templates/`, agent skills in
`.agents/skills/speckit-*`, and feature packages under `specs/00N-*/`. Work
proceeds by Spec Kit phase and dependency order. Source:
[constitution](../.specify/memory/constitution.md).

## Superpowers plans

Dated, step-by-step implementation plans under
[`docs/superpowers/plans/`](superpowers/plans/), written for agents that execute
them with the `superpowers` skills. They are execution plans subordinate to the
canonical spec and task ledger, not another ledger. Example:
[backlog resolution plan](superpowers/plans/2026-09-09-backlog-resolution.md).

## T#### task IDs

Canonical task identifiers in
[`tasks.md`](../specs/001-financial-evidence-lab/tasks.md); the first digit is
the milestone (`T0003` is M0, `T0403` is M4). Milestone packages under
`specs/002-*` onward use their own IDs (for example `M2-001`) that map onto
`T####` IDs, and the parent governs on conflict. Source:
[`AGENTS.md`](../AGENTS.md#read-before-changing-code).

## Tenant

An organization: the isolation boundary for users, workspaces, queries, runs,
and reviews, enforced by PostgreSQL row-level security (RLS). The source corpus
is shared and read-only to applications. Sources:
[spec §11.1](../specs/001-financial-evidence-lab/spec.md#111-core-entities),
[system design](architecture/system-design.md#identity-tenancy-and-authorization).

## Work package

A unit of dispatchable work registered in
[`workstreams.yaml`](handoff/workstreams.yaml) with an `id`, issue, task IDs,
`depends_on`, branch, `status` (`blocked`, `ready`, `active`, `review`, or
`merged`), and `allowed_paths`. IDs such as `M0-CONTRACTS` or `M4-MODEL-CALC`
combine a milestone code with a scope name; cross-cutting packages use names
such as `PUBLIC-GUARD-CONTROL`. Source: [handoff README](handoff/README.md#dispatch-checklist).
