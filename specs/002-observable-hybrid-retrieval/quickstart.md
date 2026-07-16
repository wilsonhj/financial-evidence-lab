# M2 Quickstart

## Prerequisites

- Current `main`, Python/Node versions from the repository, hosted disposable Supabase/Postgres with pgvector >=0.8.2.
- Apply additive M2 migration. Use mocks by default; live embedding/LLM evaluation requests credentials only when needed.

## Build a deterministic fixture index

```bash
uv run python -m fel_retrieval.index build --corpus-version "$CORPUS_VERSION" --provider mock --publish
uv run pytest packages/retrieval apps/api/tests -q
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
curl -N -H "Authorization: Bearer $FEL_TOKEN" "$FEL_API_URL/v1/queries/$QUERY_ID/events"
curl -sS -H "Authorization: Bearer $FEL_TOKEN" "$FEL_API_URL/v1/retrieval-runs/$RUN_ID"
```

Disconnect, then reconnect with `Last-Event-ID`; no events may be skipped or duplicated. Read the trace twice and compare canonical JSON hashes. A rerun must create a new run with the original run as parent.

## Compile/evaluate the smoke set

```bash
uv run python -m fel_retrieval_evals.compile evals/datasets/benchmark-seed/questions.jsonl --corpus-version "$CORPUS_VERSION" --out evals/datasets/m2-smoke/manifest.json
uv run python -m fel_retrieval_evals.run --manifest evals/datasets/m2-smoke/manifest.json --exact-baseline --report evals/reports/m2-smoke.json
uv run python -m fel_retrieval_evals.gate evals/reports/m2-smoke.json
make ci
```

The compiler fails on future evidence, missing/ambiguous quote anchors, invalid numeric ranges, or insufficient-evidence records without a pinned searched corpus. The gate prints temporal validity, Recall@10, numeric accuracy, entailment precision, completeness, ablations, and latency.

## Required negative checks

- Cross-org query/run/feedback reads return 404/403 without metadata leakage.
- A future document never appears in results, trace counts, events, or errors.
- A fact/table row from another document version cannot be cited.
- Unanchored or hash-corrupt evidence is rejected.
- Provider failure produces a terminal typed failure/abstention; it never silently changes model/config.
