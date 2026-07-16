# M2 Research and Decisions

## Existing constraints inspected

- Canonical spec/plan/tasks v1.2; issues #57–#59; ADR-0002, ADR-0004, ADR-0005.
- Corpus schema: immutable documents/versions/sections/spans/tables/facts and atomic corpus versions.
- Provider interfaces: `EmbeddingProvider` (<=512 dimensions) and `LLMProvider`.
- PR #74: 65 researched SEC questions, 10 categories, 16 issuers, all draft adjudication; four issuers uncovered and negative cases need corpus-scope verification.

## Locked decisions

1. **One Postgres system, no new service.** pgvector/Postgres FTS satisfy MVP scale and ADR-0002. HNSW supports half precision and iterative scans; PostgreSQL recommends GIN for regularly searched `tsvector` columns.
2. **Unified immutable retrieval item.** `retrieval_items` normalizes passage, fact, and table-row provenance. Dense/lexical lanes search these items; structured lanes use canonical facts/table metadata and map results back to items.
3. **Version the complete index.** An index version pins corpus version, chunker/config hash, embedding model/dimensions, and status. No in-place reindexing or cross-version mixing.
4. **Public artifacts, private analysis.** Items/embeddings/index membership inherit ADR-0004. Queries/runs/events/candidates/feedback/claims/citations carry `org_id` and RLS.
5. **Deterministic baseline planner.** Original query plus a versioned finance synonym dictionary avoids an LLM dependency in the retrieval critical path. Max four variants.
6. **RRF before reranking.** Defaults: lane 100, RRF `k=60`, fused 100, context 16. A no-op reranker keeps the interface stable. Cross-encoder is activated only if checksum-frozen smoke Recall@10 is <90%.
7. **Replay is not rerun.** Replay re-emits stored events; rerun creates a child run using pinned inputs. This removes ambiguity from UX-SRC-005.
8. **Fail closed on provenance.** A table row or passage without a unique canonical-text anchor/source span is not eligible for answer context. Index diagnostics record the rejection.
9. **Benchmark promotion, not raw adoption.** Reconcile PR #74 into main, then compile a versioned manifest mapping accessions/quotes to stable IDs. Range answers are normalized into explicit low/high fields during compilation, leaving raw seed unchanged.

## Primary-source basis

- pgvector documents `halfvec`, cosine HNSW, exact-search recall comparison, filtered-query iterative scans, and `SET LOCAL` tuning: https://github.com/pgvector/pgvector
- PostgreSQL documents GIN as preferred FTS index and safe raw-user parsing with `websearch_to_tsquery`: https://www.postgresql.org/docs/current/textsearch-indexes.html and https://www.postgresql.org/docs/current/textsearch-controls.html
- OpenAI documents `dimensions` for third-generation embeddings; request 512 dimensions rather than manually truncating: https://developers.openai.com/api/docs/guides/embeddings
- Supabase documents HNSW and `halfvec` support: https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes

## Rejected alternatives

- Elasticsearch/vector SaaS: unnecessary operational surface.
- Separate tables per lane: more joins/version rules and duplicated provenance.
- Weighted score normalization as primary fusion: scores are not comparable across lanes; RRF is simpler and locked.
- Async broker/Celery: ADR-0002 retains PostgreSQL jobs.
- LLM query planner as default: less reproducible and adds cost/failure modes.
