<!--
Sync Impact Report
- Version change: 1.1.0 -> 1.2.0
- Modified sections: Development and Review Workflow — the "sole canonical" clause
  now scopes to the canonical LEDGER (001/tasks.md) and permits subordinate
  spec/plan artifacts in milestone feature directories. Rationale: the clause was
  written when 001/ was the only feature directory. specs/002-observable-hybrid-retrieval/
  and specs/003-agentic-extraction/ have each shipped their own spec.md AND tasks.md
  since 2026-07, and specs/004-mvp-completion/ adds a subordinate plan.md, so a
  literal reading has been in breach for two months. Impact assessment: this
  legitimises existing practice rather than authorising anything new; no principle
  changes; no gate is relaxed; the single canonical task ledger is preserved, which
  is the property the clause existed to protect. Raised as finding C-1 in
  specs/004-mvp-completion/clarify-analyse.md; ruled by the integration lead
  2026-08-31.
- Modified principles: none
- Added principles: none
- Removed sections: none
- Templates: ✅ .specify/templates/plan-template.md (no change needed — it already
  describes a per-feature plan.md); ✅ .specify/templates/spec-template.md;
  ✅ .specify/templates/tasks-template.md
- Follow-up TODOs: none

Prior report (1.0.0 -> 1.1.0)
- Version change: 1.0.0 -> 1.1.0
- Modified principles: Simplicity and Provider Isolation (stack now referenced via ADR-0002, not restated); Test-First Quality Gates (gate reference updated to the canonical feature-directory spec)
- Modified sections: Approved Technical Constraints (now references docs/decisions/ADR-0002-mvp-stack.md; deck.gl removed with the deferred Embedding Atlas); Development and Review Workflow (specs/001-financial-evidence-lab/ is canonical; root SPEC.md/PLAN.md/TASKS.md are pointer stubs, no mirroring)
- Added principles: none (all five principle names retained)
- Removed sections: none
- Templates: ✅ .specify/templates/plan-template.md; ✅ .specify/templates/spec-template.md; ✅ .specify/templates/tasks-template.md
- Follow-up TODOs: none
-->
# Financial Evidence Lab Constitution

## Core Principles

### I. Evidence and Temporal Integrity
Every factual claim, extracted value, assumption, calculation, and forecast MUST retain stable provenance to immutable source data. Every query and backtest MUST enforce publication-time cutoffs. A temporal violation, unsupported factual conclusion, or cross-tenant evidence leak is a release blocker.

### II. Deterministic Financial Computation
Authoritative monetary calculations MUST use decimal arithmetic, typed units, explicit fiscal periods, and deterministic formulas. Language models MAY propose or explain assumptions but MUST NOT execute authoritative financial math. Reported, derived, user-supplied, and forecast values MUST remain distinguishable.

### III. Test-First Quality Gates
Behavior changes MUST begin with failing unit, contract, integration, property, accessibility, or evaluation tests appropriate to the risk. The numeric release gates in `specs/001-financial-evidence-lab/spec.md` Section 19.6 are mandatory. No task is complete until its tests, telemetry, documentation, and acceptance evidence pass.

### IV. Security and Cost Boundaries
Tenant isolation, least-privilege access, immutable audit events, secret protection, prompt-injection defenses, and hard cost limits are non-negotiable. Credentials MUST enter only through approved secret-management flows and MUST never be committed, logged, or copied into prompts. Billable work MUST stop at configured hard limits.

### V. Simplicity and Provider Isolation
The MVP MUST use the smallest architecture that satisfies measured requirements. The locked MVP stack is recorded in `docs/decisions/ADR-0002-mvp-stack.md` and MUST NOT be restated elsewhere. External services MUST sit behind narrow interfaces. Any stack addition or substitution — including microservices, Redis/Celery/Kafka, DuckDB-Wasm, additional AI providers, and full OpenTelemetry infrastructure — requires benchmark evidence and an approved ADR, per the change rule in ADR-0002.

## Approved Technical Constraints

- The approved stack (frontend, backend, state, AI/data providers, runtime, and revisit triggers) is defined in `docs/decisions/ADR-0002-mvp-stack.md` (Status: Accepted).
- ECharts and React Flow remain the approved charting and graph-editor libraries. deck.gl is no longer an MVP constraint; it returns with the post-MVP Embedding Atlas.
- Local development: direct Node/Python processes with mocks and hosted Supabase; Docker is optional.
- Credentials are requested only when an integration test requires them.

## Development and Review Workflow

- `specs/001-financial-evidence-lab/` holds the **sole canonical task ledger** (`tasks.md`) and the parent `spec.md` and `plan.md`. There is exactly one ledger: no other file may restate the `T####` task list or its completion state, because a duplicated ledger drifts and an agent reading the stale copy redoes merged work.
- Milestone and completion feature directories (`specs/002-*`, `specs/003-*`, `specs/004-*`, and their successors) MAY hold a subordinate `spec.md`, `plan.md`, and milestone-scoped `tasks.md` whose task IDs map onto the canonical `T####` IDs rather than replacing them. Each MUST name its parent and state that the parent governs on conflict. Root `SPEC.md`, `PLAN.md`, and `TASKS.md` are pointer stubs only; nothing is mirrored.
- Work proceeds by Spec Kit phase and dependency order. Parallel agents MUST own disjoint files or modules.
- Context7 and primary documentation MUST be consulted for version-sensitive framework behavior.
- Each logical change is reviewed against this constitution, the active feature spec, and its acceptance tests.
- GitHub `main` is protected conceptually: implementation work uses an `agent/*` branch and a reviewable pull request unless the user explicitly authorizes a direct update.

## Governance

This constitution supersedes conflicting implementation practices. Amendments require a documented rationale, impact assessment, user approval, semantic version bump, and propagation to dependent templates and active feature artifacts. Every pull request MUST include a constitution check. Unjustified complexity or a failed mandatory gate blocks merge.

**Version**: 1.2.0 | **Ratified**: 2026-07-11 | **Last Amended**: 2026-08-31
