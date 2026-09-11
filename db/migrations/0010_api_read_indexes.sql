-- ADR-0021 / #191: measured bounded read total orders.
-- 100k-row EXPLAIN (ANALYZE, BUFFERS) evidence: apps/api/HARDENING.md.
-- Additive indexes only; no evidence identities, grants or RLS changes.
CREATE INDEX workspaces_org_created_id_page_idx
    ON workspaces (org_id, created_at, id);
CREATE INDEX documents_entity_published_accession_id_page_idx
    ON documents (entity_id, published_at, accession COLLATE "C", id);
CREATE INDEX retrieval_runs_org_query_started_id_page_idx
    ON retrieval_runs (org_id, query_id, started_at, id);
CREATE INDEX document_versions_latest_parsed_page_idx
    ON document_versions (document_id, created_at DESC, parser_version COLLATE "C" DESC,
                          normalizer_version COLLATE "C" DESC, id DESC)
    WHERE status = 'parsed';
CREATE INDEX financial_facts_version_id_page_idx
    ON financial_facts (document_version_id, id);
CREATE INDEX source_spans_version_offsets_id_page_idx
    ON source_spans (document_version_id, start_char, end_char, id);
