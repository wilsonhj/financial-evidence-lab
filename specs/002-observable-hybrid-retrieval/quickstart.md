# M2 Quickstart

## Prerequisites

- Current `main`, Python/Node versions from the repository, hosted disposable Supabase/Postgres with pgvector >=0.8.2.
- Apply additive M2 migration. Use mocks by default; live embedding/LLM evaluation requests credentials only when needed.

## Build a deterministic fixture index

Index build has no CLI. `fel_retrieval.index_build` (`build_index`, `publish_index_version`, `build_and_publish`) is a library, called today only by the retrieval gate harness (`evals/harness/retrieval_gate.py`) and by tests. Install dependencies as in `docs/development/local.md`, then:

```bash
.venv/bin/pytest packages/retrieval/tests apps/api/tests/test_retrieval_api.py -q
pnpm --filter @fel/contracts test
```

Expected: a ready index version; repeated build returns the same item IDs/counts; every item hash/offset/source span verifies.

## Exercise the API

```bash
curl -sS -X POST "$FEL_API_URL/v1/workspaces/$WORKSPACE_ID/queries" \
  -H "Authorization: Bearer $FEL_TOKEN" \
  -H "Idempotency-Key: quickstart-1" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What changed in remaining performance obligations?","lanes":["dense","lexical","facts","tables"]}'
# The 202 response carries query_id, run_id and events_url (/v1/retrieval-runs/$RUN_ID/events).
curl -N -H "Authorization: Bearer $FEL_TOKEN" "$FEL_API_URL/v1/retrieval-runs/$RUN_ID/events"
curl -sS -H "Authorization: Bearer $FEL_TOKEN" "$FEL_API_URL/v1/retrieval-runs/$RUN_ID"
```

Disconnect, then reconnect with `Last-Event-ID`; no events may be skipped or duplicated. Read the trace twice and compare canonical JSON hashes. A rerun must create a new run with the original run as parent.

## Compile/evaluate the smoke set

```bash
PYTHONPATH=packages/retrieval-evals .venv/bin/python -m fel_retrieval_evals.compile \
  evals/datasets/benchmark-seed/questions.jsonl --out .local/manifest.json \
  [--corpus corpus.json] [--corpus-version "$CORPUS_VERSION"]
TEST_DATABASE_URL=... make eval-retrieval-gate
make ci
```

The compiler fails on future evidence, missing/ambiguous quote anchors, invalid numeric ranges, or insufficient-evidence records without a pinned searched corpus. `make eval-retrieval-gate` runs `evals/harness/retrieval_gate.py`: it builds an index over a corpus synthesized from the seed's quotes with the mock embedder, runs every seed question through planner, lanes and fusion, and writes `evals/reports/retrieval-gate/latest.json`. It computes Recall@10 and temporal validity and reports numeric accuracy, entailment precision and citation completeness as not evaluable, because retrieval alone generates no claims. The gate currently fails and the command exits non-zero: with the mock embedder Recall@10 is 0.4692 against the 0.9000 threshold, while temporal validity (1.0000) passes. That is expected until live embeddings land (#177, #132); do not lower the threshold. There is no separate `run` or `gate` module.

## Required negative checks

- Cross-org query/run/feedback reads return 404/403 without metadata leakage.
- A future document never appears in results, trace counts, events, or errors.
- A fact/table row from another document version cannot be cited.
- Unanchored or hash-corrupt evidence is rejected.
- Provider failure produces a terminal typed failure/abstention; it never silently changes model/config.
