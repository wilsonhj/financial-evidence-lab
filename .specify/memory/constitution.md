<!--
Sync Impact Report
- Version change: 1.1.0 -> 1.2.0
- Modified principles: none (all five principle names retained)
- Modified sections: Development and Review Workflow (canonical product specs vs additive milestone Spec Kit packages; handoff checklist authority when tasks.md lags)
- Added principles: none
- Removed sections: none
- Templates: ✅ .specify/templates/plan-template.md; ✅ .specify/templates/spec-template.md; ✅ .specify/templates/tasks-template.md
- Follow-up TODOs: none
- Prior (1.1.0): Simplicity and Provider Isolation (stack via ADR-0002); Test-First gate path; Approved Technical Constraints; specs/001 canonical vs root stubs
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

- The product MVP requirements live in `specs/001-financial-evidence-lab/`. Milestone implementation design may also live in additive Spec Kit packages (`specs/002-observable-hybrid-retrieval/`, `specs/003-agentic-extraction/`, and later). When they conflict, `001` plus Accepted ADRs win for product scope; the milestone package plus its ADR win for that milestone’s frozen contracts and task IDs. Root `SPEC.md`, `PLAN.md`, and `TASKS.md` remain pointer stubs only.
- Agents MUST NOT treat unchecked boxes in `specs/001-financial-evidence-lab/tasks.md` as blocking when `docs/handoff/workstreams.yaml` shows the corresponding package `merged`. Prefer handoff status for dispatch.
- Work proceeds by Spec Kit phase and dependency order. Parallel agents MUST own disjoint files or modules.
- Context7 and primary documentation MUST be consulted for version-sensitive framework behavior.
- Each logical change is reviewed against this constitution, the active feature spec, and its acceptance tests.
- GitHub `main` is protected conceptually: implementation work uses an `agent/*` branch and a reviewable pull request unless the user explicitly authorizes a direct update.

## Governance

This constitution supersedes conflicting implementation practices. Amendments require a documented rationale, impact assessment, user approval, semantic version bump, and propagation to dependent templates and active feature artifacts. Every pull request MUST include a constitution check. Unjustified complexity or a failed mandatory gate blocks merge.

**Version**: 1.2.0 | **Ratified**: 2026-07-11 | **Last Amended**: 2026-07-25
