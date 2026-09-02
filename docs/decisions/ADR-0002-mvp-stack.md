# ADR-0002: Locked MVP technology stack

Status: Accepted
Date: 2026-07-12

> **Amended by ADR-0012 (Proposed).** The "OpenAI for generation" pin below is
> now the *default value of a configured selection* rather than a hard-coded
> binding: ADR-0012 keeps the frozen provider protocols and adds live adapters
> behind them for OpenAI (generation and embeddings) and Anthropic (generation
> only — it has no embeddings endpoint), selected by `FEL_LLM_PROVIDER` and
> `FEL_EMBEDDING_PROVIDER`, both defaulting to OpenAI. Nothing in this ADR's
> body changes: the default is still OpenAI, `text-embedding-3` at <= 512
> dimensions stored as `halfvec` is still the embedding contract, and the final
> generation pin will be decided by the #177/#132 benchmark and recorded as an
> amendment to ADR-0012, not by editing the text below.

## Decision

This ADR is the single source of truth for the MVP technology stack. `specs/001-financial-evidence-lab/spec.md` Section 25, `plan.md` Section 4, and the constitution reference this document instead of restating the stack.

### Frontend

- Next.js 16 App Router with TypeScript and React 19.

### Backend

- FastAPI + Pydantic modular monolith plus one Python worker process.
- Supabase Postgres/pgvector, Auth, row-level security (RLS), and Storage.
- Asynchronous jobs on a PostgreSQL jobs table claimed with `FOR UPDATE SKIP LOCKED`, with `queue`/`priority` and heartbeat columns. Workers claim briefly inside a transaction and process outside it (claim-short pattern); a stale-heartbeat reaper returns abandoned jobs to the queue. Redis, Celery, and Kafka are deferred.

### AI and retrieval

- OpenAI for generation; `text-embedding-3` embeddings truncated to <= 512 dimensions and stored as `halfvec`.
- pgvector >= 0.8.2 (fixes CVE-2026-3172), with `hnsw.iterative_scan = relaxed_order` in the tuning baseline for filtered queries.
- Reciprocal rank fusion (RRF) is the first-stage fusion method. A cross-encoder reranker is added only if the frozen-benchmark Recall@10 gate fails; in that case rerank the top-100 fused candidates before any index re-engineering.

### Data providers

- Alpha Vantage as the bring-your-own market-data adapter. The paid tier (>= USD 49.99/month) is required: the free tier allows only 25 requests/day and adjusted daily series are premium-only.
- Direct SEC and FRED integrations.

### Runtime and operations

- Railway hosts the web, API, and worker processes from one monorepo.
- Sentry plus structured JSON logs for observability; full OpenTelemetry is deferred.
- GitHub Actions for CI and deployment gates.

## Revisit triggers

| Trigger | Action |
|---|---|
| > 20M vectors or sustained `ef_search` inflation to hold recall | Evaluate pgvectorscale. NOTE: pgvectorscale is unavailable on Supabase managed Postgres, so this trigger implies a database hosting move. |
| Sustained > 100 jobs/sec through the PostgreSQL queue | Move to a dedicated queue system. |
| Streamed runs > 15 minutes | Move affected streams to WebSockets (Railway enforces 5-minute-idle and 15-minute-total HTTP caps). |

## Change rule

Product-scope changes require a new specification version. Implementation-stack changes require a new ADR with benchmark evidence that the current default fails a requirement.
