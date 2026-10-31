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
`docs/decisions/**` and `specs/**` change only with an accepted ADR. The
exception is the canonical task ledger: checkbox state and per-task annotations
in `specs/001-financial-evidence-lab/tasks.md` need `contract-change` and lead
review but no ADR, unless a dispatch key, dependency or credential policy
changes. Source: [`AGENTS.md`](../AGENTS.md#shared-paths).

## allowed_paths

The list of files or globs a work package may edit, recorded on its entry in
[`workstreams.yaml`](handoff/workstreams.yaml). An agent stays inside its
issue's `allowed_paths`, and two active packages must not overlap. Source:
[`AGENTS.md`](../AGENTS.md#working-rules).

## API budget and admission

Cost ceilings checked before billable work runs: query creation and rerun take
an organization-serialized reservation against the user-daily and org-monthly
limits and return 402 `COST_LIMIT_EXCEEDED` when exceeded, with per-process 429
rate limiting alongside. Today only the retrieval query path calls it. Sources:
[ADR-0016](decisions/ADR-0016-api-budget-and-rate-limit-responses.md),
[`apps/api/app/costs.py`](../apps/api/app/costs.py).

## Approved extraction and record version

An approved extraction is a tenant-scoped `approved_extraction_records` row
(a KPI, guidance or revenue driver) whose head points at its current immutable
`approved_extraction_versions` row. Each approval or correction appends a new
version linked to its parent, so history is never rewritten; correction-history
completion is canonical task `T0309`. Sources:
[ADR-0007](decisions/ADR-0007-agentic-extraction-contract.md),
[ADR-0024](decisions/ADR-0024-extraction-review-and-conflict-occurrences.md),
[`0004_extraction_core.sql`](../db/migrations/0004_extraction_core.sql).

## BYOK (bring your own key)

User-funded inference where each user supplies their own provider credential;
there is no owner-key fallback. Source:
[ADR-0026](decisions/ADR-0026-public-workspaces-and-user-funded-inference.md).

## Calibration and `isotonic-v1`

Mapping extraction confidence scores to empirical probabilities. `isotonic-v1`
is the offline, deterministic weighted pool-adjacent-violators fitter, fitted
on calibration samples only and evaluated on disjoint held-out samples; no
runtime integration, calibrator persistence or auto-approval is authorized.
Sources: [ADR-0028](decisions/ADR-0028-offline-calibration-primitives.md),
[`ISOTONIC.md`](../workers/src/fel_workers/extraction/ISOTONIC.md).

## Checkpoint and stage output

A completed extraction stage's result, stored in `extraction_run_steps.output`
beside its `output_hash` so a crashed run resumes from the next incomplete step
without repeating model calls. ADR-0009 had carried it in the `step_completed`
event payload; ADR-0011 superseded that, and event payloads are metadata-only.
Sources: [ADR-0011](decisions/ADR-0011-extraction-step-output-column.md),
[ADR-0009](decisions/ADR-0009-checkpoint-payload-in-event-stream.md) (superseded).

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

## Conflict occurrence

One instance of an extraction conflict group, keyed by `conflict_key` plus
`occurrence_run_id`. Runs pinned to the `run/v1` policy get their own
occurrence, so a child run starts with an independent group and no inherited
approval; legacy rows keep a NULL, workspace-wide occurrence. Source:
[ADR-0024](decisions/ADR-0024-extraction-review-and-conflict-occurrences.md#conflict-occurrence-persistence).

## contract-change

The GitHub label required on every pull request that edits a
[shared path](#shared-paths). Depending on the class of change it also needs an
accepted ADR or an integration-lead authorization record. Source:
[`AGENTS.md`](../AGENTS.md#shared-paths).

## Corpus version and corpus pin

A corpus version is an immutable, atomically published set of parsed document
versions (`corpus_versions` with status `draft`, `active` or `superseded`). A
corpus pin is a `corpus_version_id` passed to a read, which selects exactly the
document versions in that set instead of the latest parsed ones; drafts are not
addressable. Sources:
[ADR-0005](decisions/ADR-0005-reader-composite-endpoint.md),
[ADR-0021](decisions/ADR-0021-bounded-api-pagination-and-reader.md).

## Deployment mode

The operator-selected `FEL_DEPLOYMENT_MODE`: `public` (the default, also
accepted as an explicit value), `fixture`, `reader-smoke`, or `synthetic-http`.
Public mode refuses business web routes with HTTP 503 rather than using a
shared deployment identity, while the public API still accepts independently
verified Supabase identities (`FEL_AUTH_MODE=supabase`). Sources:
[ADR-0027](decisions/ADR-0027-deployment-modes.md),
[`apps/api/app/config.py`](../apps/api/app/config.py),
[`apps/api/app/deployment.py`](../apps/api/app/deployment.py).

## Earnings Update Desk

The web view at `/desk`: an illustrative earnings review with lineage
graphics, scenario charts and approval gates, rendered entirely from static
fixtures with nothing computed. No ADR governs it. Source:
[`apps/web/src/app/desk/`](../apps/web/src/app/desk/page.tsx).

## Evidence

Source material and everything derived from it with provenance: immutable
documents and versions, sections, passages, tables, normalized facts, and
source spans. Evidence is versioned, never silently rewritten. Sources:
[spec §11.1](../specs/001-financial-evidence-lab/spec.md#111-core-entities),
[architecture overview](architecture/overview.md).

## Evidence Reader

The web view at `/reader/[documentId]` that renders one filing version with its
sections, source spans and facts beside same-entity siblings, backed by the
version-pinned composite endpoint `GET /v1/documents/{documentId}/reader`
under an inclusive `as_of` cutoff. Sources:
[ADR-0005](decisions/ADR-0005-reader-composite-endpoint.md),
[`EvidenceReader.tsx`](../apps/web/src/components/EvidenceReader.tsx).

## Extraction run

One execution of the bounded extraction state machine for a workspace entity,
pinned at creation to its cutoff, corpus version, ontology, workflow, provider,
model and budget caps (`extraction_runs`). It moves through `queued`,
`running` and `waiting_review` to a terminal `succeeded`, `failed` or
`cancelled`, and proposals from it are approved only by a human. Source:
[ADR-0007](decisions/ADR-0007-agentic-extraction-contract.md).

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

## Golden file and gates

A golden file is committed expected output that a test compares exactly, such
as the retrieval-gate report or `evals/tests/golden/corpus-qa/`. Exit gates are
each milestone's objective acceptance criteria; the smoke gates are the
checksum-frozen M2 smoke benchmark and the reader production smoke; the
retrieval gate grades Recall@10 and temporal validity, and CI matches the
graded section to the committed report and does not fail the build on the
live Recall threshold.
Sources: [plan §3](../specs/001-financial-evidence-lab/plan.md#3-milestones),
[spec §19.6](../specs/001-financial-evidence-lab/spec.md#196-release-gates),
[retrieval-gate schema](../evals/reports/retrieval-gate/SCHEMA.md).

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

## Migration ledger

The `schema_migrations` table, one row per applied migration file with its
SHA-256 checksum, written only by `scripts/db/migrate.py`, which fails closed
on drift. It is unrelated to the canonical task ledger and the handoff ledgers
(see [Ledger](#ledger)). ADR-0014 is still Proposed although the design is
live. Sources: [ADR-0014](decisions/ADR-0014-migration-ledger-and-applier.md),
[`scripts/db/migrate.py`](../scripts/db/migrate.py).

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

## Retrieval index version and lane

A retrieval index version is an immutable build pinned to one published corpus
version, chunker config hash and embedding provider/model (512 dimensions);
changing any input creates a new version. A lane is one of the four retrieval
paths, `dense`, `lexical`, `facts` and `tables`, whose candidates are fused by
[RRF](#rrf-reciprocal-rank-fusion). Source:
[ADR-0006](decisions/ADR-0006-observable-retrieval.md).

## Retrieval receipt

Provenance for a non-SEC provider fetch (FRED, Alpha Vantage): the source and
final URL with credentials redacted, retrieval time, status, content type, byte
length, SHA-256 of the decoded body and attempt count. It travels with (or beside) the
values parsed from that body and never counts toward their equality. Sources:
[ADR-0029](decisions/ADR-0029-retrieval-receipts.md),
[`workers/src/fel_workers/http.py`](../workers/src/fel_workers/http.py).

## Retrieval trace

The ordered, persisted `retrieval_events` (with per-lane candidates) of one
retrieval run, each committed before it is streamed. Replay re-emits the stored
trace and creates no data; an unchanged rerun creates a child run pinned to the
original inputs. Source:
[ADR-0006](decisions/ADR-0006-observable-retrieval.md).

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

## Source clock

A time a provider reports about its own data inside a response, such as ALFRED's
real-time window or Alpha Vantage's last-refreshed date and time zone, recorded
verbatim with its JSON Pointer on the retrieval receipt. Adapters read clocks
only from explicit allowlists, and nothing infers freshness from them. Source:
[ADR-0031](decisions/ADR-0031-named-source-clocks.md).

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

## Vintage and missing observation

A vintage is a series as it was known at a cutoff (`VintageObservation`: series,
date, value, `as_of`), from vintage-aware FRED/ALFRED ingestion (`T0107`). A
missing observation is a date the vintage covers but publishes no value for
(ALFRED `"."`); it is kept as an explicit record, never a zero or
carried-forward value. Sources:
[ADR-0030](decisions/ADR-0030-explicit-fred-missing-values.md),
[`fred.py`](../workers/src/fel_workers/ingestion/fred.py).

## Work package

A unit of dispatchable work registered in
[`workstreams.yaml`](handoff/workstreams.yaml) with an `id`, issue, task IDs,
`depends_on`, branch, `status` (`blocked`, `ready`, `active`, `review`, or
`merged`), and `allowed_paths`. IDs such as `M0-CONTRACTS` or `M4-MODEL-CALC`
combine a milestone code with a scope name; cross-cutting packages use names
such as `PUBLIC-GUARD-CONTROL`. Source: [handoff README](handoff/README.md#dispatch-checklist).

## Worker role (`fel_app` / `fel_worker`)

The non-login PostgreSQL roles that runtime connections switch to. API request
paths run as `fel_app` (`SET LOCAL ROLE`) with the caller's claims; the Railway
worker selects `fel_worker` through `FEL_WORKER_DB_ROLE` and keeps migration
authority on a separate connection. Sources:
[ADR-0020](decisions/ADR-0020-worker-role-rollout.md),
[ADR-0004](decisions/ADR-0004-public-corpus-tenancy.md).

## Workspace

A tenant-owned analysis context for one entity with a base currency, fiscal
calendar, as-of cutoff and active scenario (`workspaces`); runs, reviews and
approved records are scoped to it. Sources: `T0006` in the
[canonical ledger](../specs/001-financial-evidence-lab/tasks.md),
[`apps/api/app/workspaces.py`](../apps/api/app/workspaces.py).
