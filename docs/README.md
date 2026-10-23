# Documentation index

Every Markdown document in the repository, grouped by who needs it and then by
purpose. Tier labels:

- **core**: read first for your role.
- **supporting**: read when you work in that area.
- **reference**: look up when needed; often dated evidence or history.

Live delivery state lives only in [`handoff/STATUS.md`](handoff/STATUS.md) and
GitHub. Terms are defined in the [glossary](glossary.md).

## Start here

- **Humans:** [`README.md`](../README.md) →
  [architecture overview](architecture/overview.md) →
  [local development](development/local.md).
- **Agents:** [`AGENTS.md`](../AGENTS.md), which sets the reading order for a
  first session. To resume work, follow the resume sequence in
  [`CLAUDE.md`](../CLAUDE.md).

## By audience

| Audience | Core docs | Then see |
|---|---|---|
| New contributor | [README](../README.md), [architecture overview](architecture/overview.md), [local development](development/local.md), [testing guide](development/testing.md) | [Architecture](#architecture), [Development](#development), [Packages and apps](#packages-and-apps) |
| AI agent / orchestrator | [`AGENTS.md`](../AGENTS.md), [handoff README](handoff/README.md), [`STATUS.md`](handoff/STATUS.md), [`workstreams.yaml`](handoff/workstreams.yaml), [Fable orchestration](handoff/FABLE_ORCHESTRATION.md) | [Handoff](#handoff-and-coordination), [Specifications](#specifications), [Decisions](#decisions) |
| Reviewer | [quality gates](development/quality-gates.md), [required checks](../.github/required-checks.md), [handoff README: reviewing ledger changes](handoff/README.md#reviewing-ledger-changes) | [Decisions](#decisions), [Evaluation and acceptance evidence](#evaluation-and-acceptance-evidence) |
| Operator | [runbooks](#runbooks), [production auth notes](handoff/production-auth.md), [Railway configuration](../infra/railway/README.md) | [Infrastructure and tooling](#infrastructure-and-tooling) |

## Architecture

| Doc | Description | Tier |
|---|---|---|
| [Architecture overview](architecture/overview.md) | Components, layers, trust boundaries, and invariants present on `main` | **core** |
| [System design](architecture/system-design.md) | Tenancy, temporal model, ingestion, retrieval, extraction, and failure semantics | **core** |

## Development

| Doc | Description | Tier |
|---|---|---|
| [Local development](development/local.md) | Toolchain, fixture UI, local PostgreSQL/API setup, and environment variables | **core** |
| [Testing guide](development/testing.md) | Test boundaries, the suite matrix, and developer loops | **core** |
| [Quality gates](development/quality-gates.md) | Measured regression floors for the Python and JavaScript gates | supporting |
| [Doc page template](templates/doc-page.md) | Header, footer and section conventions for documentation pages | supporting |

## Runbooks

| Doc | Description | Tier |
|---|---|---|
| [Extraction worker](runbooks/extraction-worker.md) | Operating `extraction_run` jobs on the extraction queue | **core** |
| [Unit policy migration](runbooks/unit-policy-migration.md) | Deploying the ADR-0019 unit comparison policy | supporting |
| [Guidance range policy migration](runbooks/guidance-range-policy-migration.md) | Deploying the ADR-0022 signed guidance range policy | supporting |
| [Extraction operator notes](../workers/src/fel_workers/extraction/OPERATOR.md) | Operator notes kept beside the extraction worker code | supporting |

## Handoff and coordination

| Doc | Description | Tier |
|---|---|---|
| [Handoff README](handoff/README.md) | Restart point: source-of-truth order, ledger review rules, dispatch checklist | **core** |
| [`STATUS.md`](handoff/STATUS.md) | Dated implementation status, newest section first; the live status source | **core** |
| [`workstreams.yaml`](handoff/workstreams.yaml) | Work-package registry: dependencies, branches, status, `allowed_paths` | **core** |
| [Fable orchestration](handoff/FABLE_ORCHESTRATION.md) | Scheduling loop, worker prompt, and reassignment rules | supporting |
| [Contract freeze protocol](handoff/CONTRACTS.md) | What the M0 contract freeze covers | supporting |
| [Credential registry](handoff/CREDENTIALS.md) | Credential names and ownership only, never values | supporting |
| [Production auth notes](handoff/production-auth.md) | Configuring the ADR-0025 Supabase token verifier | supporting |
| [Implementation agents, 2026-09-16](handoff/implementation-agents-2026-09-16.md) | Current external implementation cards for #336 and #337 | supporting |
| [External agents, 2026-09-16](handoff/external-agents-2026-09-16.md) | Bounded external research and review cards | supporting |
| [Execution record, 2026-09-09](handoff/execution-2026-09-09.md) | Per-issue execution evidence from the September backlog run | reference |
| [External agent brief](handoff/EXTERNAL_AGENT_BRIEF.md) | July 2026 EXT preparation items (historical) | reference |
| [SEC egress session brief](handoff/SESSION_BRIEF_SEC_EGRESS.md) | July 2026 EXT execution session (historical) | reference |
| [EXT executor brief v2](handoff/EXT_EXECUTOR_BRIEF_V2.md) | July 2026 git-only EXT executor brief (historical) | reference |

## Decisions

| Doc | Description | Tier |
|---|---|---|
| [ADR index](decisions/README.md) | Every architecture decision record with its status | **core** |
| [ADR-0002 MVP stack](decisions/ADR-0002-mvp-stack.md) | The locked MVP stack and its change rule | **core** |

## Specifications

The parent package governs; later packages are subordinate and name their parent.
Root `SPEC.md`, `PLAN.md`, and `TASKS.md` are pointer stubs only.

| Doc | Description | Tier |
|---|---|---|
| [001 spec](../specs/001-financial-evidence-lab/spec.md) | Canonical product and technical specification | **core** |
| [001 plan](../specs/001-financial-evidence-lab/plan.md) | Workstreams, milestones M0–M5, and exit gates | **core** |
| [001 tasks](../specs/001-financial-evidence-lab/tasks.md) | The sole canonical task ledger (`T####`) | **core** |
| [001 requirements checklist](../specs/001-financial-evidence-lab/checklists/requirements.md) | Specification quality checklist | reference |
| [002 observable hybrid retrieval](../specs/002-observable-hybrid-retrieval/) | M2 spec, data model, research, quickstart, tasks, clarify/analyse | supporting |
| [003 agentic extraction](../specs/003-agentic-extraction/) | M3 spec, data model, research, quickstart, tasks, clarify/analyse | supporting |
| [004 MVP completion](../specs/004-mvp-completion/) | Release specification, plan, clarify/analyse | supporting |
| [005 M3 completion](../specs/005-m3-completion/) | Remaining M3 work: spec, plan, clarify/analyse | supporting |
| [Constitution](../.specify/memory/constitution.md) | Project principles and Spec Kit governance | **core** |

## Research

| Doc | Description | Tier |
|---|---|---|
| [Research index](research/README.md) | Every research note with its date and status | supporting |
| [Completion spec, 2026-09-16](research/2026-09-16-completion-spec.md) | Owner-requested completion specification | supporting |
| [Model and scenario design, 2026-09-11](research/2026-09-11-model-scenario-design.md) | Research note for #64 models and sparse scenarios | reference |
| [Backlog resolution spec, 2026-09-09](research/2026-09-09-backlog-resolution-spec.md) | Open-backlog resolution specification | reference |
| [Open issue audit, 2026-09-09](research/2026-09-09-open-issue-audit.md) | Read-only audit of 39 open issues | reference |
| [Reconciliation, 2026-07-16](research/RECONCILIATION-2026-07-16.md) | Audit of the PR #74/#75 research recovery | reference |
| [Deployment guard contract](research/deployment-guard-contract.md) | Frozen ADR-0027 guard implementation contract | supporting |
| [Offline calibration contract](research/offline-calibration-contract.md) | Frozen ADR-0028 contract for #336/#337 | supporting |
| [Public auth and BYOK contract](research/public-auth-byok-contract.md) | Proposed public-session and BYOK contract (not frozen) | reference |
| [Evals report renderer proposal](research/evals-report-renderer-proposal.md) | Unapproved work-package draft | reference |
| [FinRobot study: calc engine](research/finrobot-cherry-pick-calc-engine.md) | Cherry-pick study for the M4 calculation engine | reference |
| [FinRobot study: extraction agents](research/finrobot-cherry-pick-extraction-agents.md) | Cherry-pick study for M3 extraction roles | reference |
| [Ontology research](research/ontology/README.md) | EXT-3 SaaS disclosure research draft | reference |
| [SaaS disclosure survey](research/ontology/saas-disclosure-survey.md) | Raw survey feeding the T0301 ontology | reference |

## Implementation plans

| Doc | Description | Tier |
|---|---|---|
| [`superpowers/plans/`](superpowers/plans/) | Dated step-by-step agent execution plans, subordinate to the spec and task ledger | reference |

## Packages and apps

| Doc | Description | Tier |
|---|---|---|
| [Shared packages](../packages/README.md) | Package table with purpose, language, and docs | **core** |
| [API service](../apps/api/README.md) | FastAPI routes and services | supporting |
| [API hardening](../apps/api/HARDENING.md) | ADR-0021 bounded reads and compatibility | supporting |
| [API performance](../apps/api/PERFORMANCE.md) | SQL-operation budgets and performance checks | supporting |
| [Extraction load acceptance](../apps/api/EXTRACTION_LOAD.md) | Opt-in #61 extraction HTTP load benchmark | reference |
| [Web app](../apps/web/README.md) | Next.js evidence reader and Search Observatory | supporting |
| [Workers](../workers/README.md) | Job consumer, ingestion, and extraction runtime | supporting |
| [Calculation engine](../packages/calculation-engine/README.md) | Decimal calculation engine (M4) | supporting |
| [Contracts](../packages/contracts/README.md) | Frozen OpenAPI/JSON Schema contracts | supporting |
| [Contract versioning](../packages/contracts/VERSIONING.md) | Frozen contract versioning rules | supporting |
| [Ontology](../packages/ontology/README.md) | `saas-metrics/v1` ontology | supporting |
| [Retrieval](../packages/retrieval/README.md) | Hybrid retrieval backend (M2) | supporting |
| [Retrieval evals](../packages/retrieval-evals/README.md) | Benchmark manifest compiler and gate metrics | supporting |
| [UI](../packages/ui/README.md) | Reserved shared UI package | reference |
| [OpenAI structured adapter](../packages/providers/OPENAI.md) | Explicit-key structured generation adapter | supporting |
| [OpenAI embeddings adapter](../packages/providers/OPENAI_EMBEDDINGS.md) | Explicit-key 512-dimension embeddings adapter | supporting |
| [Credential cipher](../packages/providers/CREDENTIAL_CIPHER.md) | Offline credential encryption | supporting |
| [Migrations](../db/migrations/README.md) | Append-only SQL migrations and their order | supporting |
| [Seeds](../db/seeds/README.md) | Development and test seed data | reference |

## Evaluation and acceptance evidence

| Doc | Description | Tier |
|---|---|---|
| [Retrieval acceptance](../packages/retrieval/ACCEPTANCE.md) | M2-RETRIEVAL-BACKEND (#57) acceptance report | reference |
| [Observatory acceptance](../apps/web/ACCEPTANCE.md) | M2-OBSERVATORY-UI (#59) acceptance report | reference |
| [Accessibility audit](../apps/web/ACCESSIBILITY.md) | WCAG 2.2 AA audit of the Observatory and reader | reference |
| [Calculation engine #219 acceptance](../packages/calculation-engine/ACCEPTANCE-219.md) | Local acceptance evidence for #219 | reference |
| [Eval report renderers](../evals/reporting/README.md) | Deterministic renderers for committed reports | supporting |
| [Corpus-QA report schema](../evals/reports/corpus-qa/SCHEMA.md) | `corpus-qa-report/v1` schema | reference |
| [Retrieval-gate report schema](../evals/reports/retrieval-gate/SCHEMA.md) | `retrieval-gate-report/v1` schema | reference |
| [Reader production smoke](../evals/reports/reader-prod-smoke/README.md) | #108 harness notes (not a hosted result) | reference |
| [Local reader smoke, 2026-09-14](../evals/reports/reader-prod-smoke/2026-09-14-local-smoke.md) | Local #108 preparation evidence | reference |
| [Synthetic corpus-QA cohort](../evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.md) | Synthetic golden report; explicitly not acceptance-grade | reference |
| [Benchmark seed](../evals/datasets/benchmark-seed/README.md) | EXT-1 candidate benchmark questions | reference |
| [Reader cross-stack dataset](../evals/datasets/reader-cross-stack/README.md) | READER-CROSS-STACK (#96) verification | reference |
| [SEC fixtures](../evals/datasets/sec-fixtures/README.md) | Historical SEC fixture manifest (unverified recovery) | reference |
| [SEC fixture excerpts](../evals/datasets/sec-fixtures/excerpts/README.md) | Notes that no excerpt bytes were recovered | reference |

## Infrastructure and tooling

| Doc | Description | Tier |
|---|---|---|
| [Infrastructure](../infra/README.md) | Platform configuration overview | supporting |
| [Railway services](../infra/railway/README.md) | Railway config-as-code per service | supporting |
| [Python runtime locks](../scripts/runtime/README.md) | Reproducible Python runtime lock files | supporting |
| [Required checks](../.github/required-checks.md) | Required pull-request check names for `main` | supporting |
| [PR template](../.github/PULL_REQUEST_TEMPLATE.md) | Pull request evidence template | supporting |
| [Spec Kit skills](../.agents/skills/) | `speckit-*` agent skills | reference |
| [Spec Kit templates](../.specify/templates/) | Spec, plan, task, checklist, and constitution templates | reference |
