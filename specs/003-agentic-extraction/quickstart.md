# M3 Quickstart

## Preconditions

1. Start from current `main`; M2 claims verification and contract-change issue #101 must be merged.
2. Use a disposable PostgreSQL/Supabase development database with migrations applied.
3. No credential is needed for CI or local mock flows. A live smoke later requires `FEL_OPENAI_API_KEY` through approved secret handling.

## Expected commands

```bash
pnpm install --frozen-lockfile
uv sync --all-packages --dev
make db-migrate
make ci
# Contract tests iterate every value in contracts/fixtures/extraction-payloads.valid.json
# against contracts/schemas/extraction-payload.schema.json and check generated drift.
uv run pytest workers/tests/extraction -q
uv run pytest apps/api/tests/test_extraction_api.py -q
pnpm --filter @fel/web test -- extraction
uv run pytest evals/tests/test_extraction_gates.py -q
```

## Mock acceptance flow

1. Seed one organization, owner/editor/reviewer/viewer, workspace cutoff, active corpus version, a filing with two sections, verified source spans, facts/table, and M2 citations including one conflict.
2. POST `/v1/workspaces/{id}/extraction-runs` with a stable `Idempotency-Key`, required `entity_id` + `as_of`, modes `kpi,guidance,revenue_driver`, pinned span IDs, and budgets at or below policy.
3. Run the extraction worker against `MockStructuredLLMProvider`; poll/stream events and assert fixed stage order, versions, counters, and `waiting_review`.
4. Replay the POST and verify the same run/job ID.
5. Review a non-first-section KPI, a monetary guidance range, and a driver. Verify exact global span hashes and proposal blockers.
6. Accept/edit/reject using an expected version for every selected proposal; merge only compatible duplicates; rerun creates a child run. Correct an approved record with `If-Match` and verify a child version is created while the prior version remains immutable.
7. Move workspace cutoff earlier and assert direct run/proposal creation with later evidence fails without revealing the resource.

## Failure drills

- Kill the worker after each checkpoint and verify resume without duplicate calls.
- Return invalid JSON twice, a provider refusal, timeout, over-budget usage, malicious filing instructions, reversed guidance bounds, mismatched scale, corrupt span hash, cross-version evidence, and cross-tenant IDs.
- Race two reviewers with the same per-proposal expected versions; exactly one commits and the other gets 412. Repeat for two approved-record corrections with the same `If-Match`.
- Disconnect SSE, reconnect with `Last-Event-ID`, and receive each missed event once.

## Release evidence

Attach to each PR: commit SHA, task IDs, tests/CI, schema/client drift result, migration/RLS evidence where applicable, mock trace, credential status, remaining limitations, and independent review link. M3 exit also attaches versioned extraction metrics meeting 90% guidance F1, 88% KPI/driver F1, and 99% numeric accuracy.
