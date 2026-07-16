# ADR-0006: Versioned observable retrieval and trace replay

Status: Accepted  
Date: 2026-07-16  
Accepted: 2026-07-16 by integration lead on merge of PR #102  
Occasioned by: M2 / issues #57–#59

## Decision

1. Store retrieval in existing Supabase Postgres/pgvector. No new search service or queue.
2. Add an immutable `retrieval_index_version` pinned to one published corpus version, chunker/config hash, embedding provider/model and 512 dimensions. Its UUIDv5 and unique tuple are deterministic, so an identical build reuses/resumes the same row; changing any pinned input creates a new version. Index publication is atomic. Land these tables (and tenant-scoped query/trace/claim tables) in additive migration `0003_retrieval_core.sql` before M3’s `0004_extraction_core.sql`.
3. Normalize passage, table-row and fact representations into shared `retrieval_items`. Items and embeddings are public-corpus-derived, carry no `org_id`, and are SELECT-only to `fel_app` under ADR-0004. Every context-eligible item must resolve to a hash-verifiable source span from the same selected document version.
4. Queries, runs, events, candidates, feedback, claims and citations are tenant-created analysis records. They carry `org_id`, enforce RLS, and are unavailable cross-tenant.
5. Baseline retrieval is deterministic: original query plus versioned synonym expansions (max four), four concurrent lanes, lane top-100, RRF `k=60`, fused top-100 and context top-16. A no-op reranker interface ships. If the checksum-frozen M2 smoke baseline Recall@10 is below 90%, add a cross-encoder over the fused top 100 as ADR-0002 requires.
6. Dense indexing uses OpenAI `text-embedding-3-small` requested at 512 dimensions, `halfvec(512)`, cosine HNSW, and filtered-query `hnsw.iterative_scan=relaxed_order`. Lexical indexing uses English `tsvector`, GIN, `websearch_to_tsquery`, and `ts_rank_cd`. Exact vector search is the recall oracle.
7. Every trace event is committed before SSE emission with a monotonically increasing sequence. **Replay** re-emits the stored trace and creates no data. **Unchanged rerun** creates a child run pinned to the original immutable plan/index/model inputs. A user control change creates a new child query with `parent_query_id`, its own immutable plan, and a comparable child run. SSE supports `Last-Event-ID` and 15–30 second heartbeats.
8. PR #74’s raw seed is reconciled into main but is not itself the executable gate. A compiler resolves quotes/accessions to unique stable evidence IDs in a pinned corpus and emits a checksum-frozen M2 smoke manifest. Failure to resolve uniquely, temporal leakage, or unspecified negative-case corpus scope fails compilation.

## Consequences

- An additive DB migration and additive OpenAPI minor version are required before parallel implementation.
- Public retrieval artifacts may be reused across tenants without leaking tenant questions.
- Stored replay is exactly reproducible even if ANN/provider behavior later changes; reruns remain comparable through explicit parent/config hashes.
- Unanchored table rows are excluded rather than cited approximately.

## Revisit triggers

- ADR-0002 scale triggers (>20M vectors or sustained `ef_search` inflation).
- Smoke Recall@10 <90% activates the reranker path before index redesign.
- Planner synonym coverage materially fails benchmark categories: propose a versioned structured LLM planner, not an implicit fallback.
