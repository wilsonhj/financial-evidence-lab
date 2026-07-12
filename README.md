# Financial Evidence Lab

Implementation specification for a highly visual, evidence-first financial research application combining hybrid retrieval, agentic extraction, forecasting, and interactive revenue modeling.

## Documents

- [`SPEC.md`](./SPEC.md) — product, UX, architecture, data, API, evaluation, security, and delivery specification.
- [`PLAN.md`](./PLAN.md) — implementation sequence, architecture workstreams, and milestone gates.
- [`TASKS.md`](./TASKS.md) — dependency-ordered, testable implementation backlog mapped to the specification.
- [`AGENTS.md`](./AGENTS.md) — operating contract for internal and external coding agents.
- [`docs/handoff/`](./docs/handoff/) — resumable Claude Code/Fable orchestration state and work queue.
- [`.specify/`](./.specify/) — GitHub Spec Kit configuration, constitution, scripts, and templates.
- [`specs/001-financial-evidence-lab/`](./specs/001-financial-evidence-lab/) — Spec Kit feature artifacts used by `$speckit-implement`.

## Product thesis

Financial analysis should not force users to choose between conversational AI, document search, and spreadsheet modeling. Financial Evidence Lab connects them in one auditable workspace: every generated claim, extracted fact, forecast, and model output remains linked to its source evidence and calculation lineage.

## Proposed MVP

1. Select a public company and point-in-time cutoff.
2. Ingest its SEC filings and normalized XBRL facts.
3. Ask a financial question using visible hybrid retrieval.
4. Review agent-extracted revenue drivers and citations.
5. Build bull/base/bear scenarios in a visual driver graph.
6. Inspect forecast ranges, sensitivities, and provenance.
7. Export an evidence-backed research brief.

## Status

Specification clarified with team SaaS, B2B SaaS, revenue/gross-profit modeling, Embedding Atlas, Supabase, OpenAI, Alpha Vantage, Railway, and a PostgreSQL job queue as the locked MVP defaults. GitHub Spec Kit 0.12.11 is initialized in Codex skills mode. No production code has been implemented yet.
