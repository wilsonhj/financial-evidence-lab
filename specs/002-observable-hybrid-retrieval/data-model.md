# M2 Data Model

All tables are additive. UUIDs are v4 unless a deterministic v5 rule is stated. JSON payloads validate against versioned contracts.

## Shared immutable retrieval artifacts (no `org_id`, SELECT-only `fel_app`)

### `retrieval_index_versions`

`id` (UUIDv5 of corpus version/config hash/provider/model/dimensions/distance), `corpus_version_id`, `status(draft|building|ready|failed|superseded)`, `chunker_version`, `chunker_config`, `config_hash`, `embedding_provider`, `embedding_model`, `dimensions=512`, `distance=cosine`, `created_at`, `published_at`, `diagnostics`. Unique `(corpus_version_id,config_hash,embedding_provider,embedding_model,dimensions,distance)`; an identical build resumes or returns the existing row rather than minting a new version. Exactly one ready active default; query may pin any ready/superseded published version.

### `retrieval_items`

`id` (UUIDv5 of index/kind/source-anchor/content hash), `index_version_id`, `kind(passage|table_row|fact)`, `entity_id`, `document_id`, `document_version_id`, `section_id`, `source_span_id`, nullable `financial_fact_id`, nullable `table_id`/`table_row_index`, `content`, `content_sha256`, `heading_path`, global `start_char`/`end_char`, `token_count`, `metadata`, generated `search_vector`, `created_at`.

Constraints: exactly one kind-specific anchor; span/document/section versions must agree; offsets/hash must reverify; unique `(index_version_id,kind,source_anchor,content_sha256)`.

Indexes: B-tree on index/entity/document/form/period fields; GIN on `search_vector`; HNSW is on embeddings.

### `retrieval_embeddings`

`retrieval_item_id`, `index_version_id`, `provider`, `model`, `dimensions`, `embedding halfvec(512)`, `content_sha256`, `created_at`; primary key `(retrieval_item_id,provider,model,dimensions)`. HNSW cosine index with default `m=16, ef_construction=64`; query uses `SET LOCAL hnsw.iterative_scan=relaxed_order` and records `ef_search`.

## Tenant-scoped analysis records (all `org_id` + RLS)

### `queries`

Immutable query version: `id`, `org_id`, `workspace_id`, `created_by`, `question`, `effective_as_of`, `corpus_version_id`, `index_version_id`, `plan`, `planner_version`, `config`, nullable `parent_query_id`, `created_at`.

### `retrieval_runs`

`id`, `org_id`, `query_id`, nullable `parent_run_id`, `mode(execute|rerun)`, `status`, `config_hash`, provider/model versions, budget/cost, start/end timestamps, terminal error. A stored-trace replay does not create a row.

### `retrieval_events`

`run_id`, `org_id`, `seq bigint`, `event_type`, `payload`, `created_at`; primary key `(run_id,seq)`. Append-only; event ID is decimal `seq`.

### `retrieval_candidates`

`id`, `org_id`, `run_id`, `retrieval_item_id`, `lane(dense|lexical|facts|tables)`, `variant_index`, `lane_rank`, decimal-string `raw_score`, nullable decimal-string `normalized_score`, `rrf_contribution`, nullable `fused_rank`/`rerank_rank`, `accepted`, `rejection_code`, `timing_ms`, `created_at`. Unique per run/lane/variant/item.

### `retrieval_feedback`

`id`, `org_id`, `run_id`, `retrieval_item_id`, `label(relevant|irrelevant|duplicate|temporally_invalid)`, `actor_user_id`, `reason`, `created_at`; append-only corrections supersede by link.

### `claims` and `citations`

Claims: `id`, `org_id`, `run_id`, `ord`, `text`, `status`, nullable decimal-string confidence, deterministic calculation lineage, `created_at`.

Citations: `id`, `org_id`, `claim_id`, `retrieval_item_id`, `source_span_id`, `status(entailed|partial|contradictory|irrelevant)`, verifier/model/version, numeric-check JSON, rationale, `created_at`. Foreign-key/version checks prevent dangling or cross-version evidence.

## State machines

- Index: `draft -> building -> ready|failed`; `ready -> superseded`. Publish is atomic.
- Run: `queued -> planning -> retrieving -> fusing -> generating -> verifying -> succeeded|abstained|failed|cancelled`.
- Events/candidates/claims/citations are append-only after terminal run.

## Deletion/retention

Shared index artifacts are immutable and superseded, not overwritten. Tenant run payloads follow the canonical 365-day query retention; audit metadata follows the seven-year policy. Deletion must be org-scoped and preserve required audit hashes.
