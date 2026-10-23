# API (`apps/api`)

<details>
<summary>Relevant source files</summary>

- [app/main.py](app/main.py) — FastAPI app, router registration, error envelope, `/health`
- [app/config.py](app/config.py) — `Settings`: every environment variable the API reads
- [app/deployment.py](app/deployment.py) — fail-closed deployment guard (ADR-0027)
- [app/dependencies.py](app/dependencies.py) — verifier selection and membership lookup
- [app/auth.py](app/auth.py), [app/supabase_auth.py](app/supabase_auth.py) — mock and Supabase token verifiers
- [app/db.py](app/db.py) — connection pool and tenant-scoped transactions
- [app/workspaces.py](app/workspaces.py), [app/corpus.py](app/corpus.py), [app/reader.py](app/reader.py), [app/retrieval.py](app/retrieval.py) — route modules
- [app/extraction/](app/extraction/) — extraction run, review, history and event routes
- [pyproject.toml](pyproject.toml) — package metadata and runtime dependencies
- [tests/](tests/) — API test suite

</details>

Source references verified against commit `437ce55`.

`fel-api` is the FastAPI service between the Next.js application and
PostgreSQL. It verifies identity, resolves the caller's membership from the
database, opens a tenant-scoped transaction, and serves the workspace, corpus,
reader, retrieval, and extraction APIs. This page is for developers running or
changing the service; the request path and tenancy model are described in
[System design](../../docs/architecture/system-design.md).

## Entrypoint

The ASGI application is `app.main:app`. It configures logging and error
reporting, registers request-context middleware, and owns the database pool
for the process lifetime. Every error is returned in one envelope:
`{"error": {"code", "message", "details", "request_id"}}`.

`GET /health` returns a static `{"status", "service", "version"}` payload and
needs no authentication.

## Run locally

Follow [Local development, option B](../../docs/development/local.md#option-b-local-postgresql-and-api)
to start PostgreSQL, apply migrations, seed a tenant, and mint a mock token.
The API itself starts with:

```sh
PYTHONPATH=apps/api:packages/providers:packages/retrieval:packages/ontology:workers/src \
  .venv/bin/uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload
```

The explicit `PYTHONPATH` is required: the route modules import the sibling
`fel_providers`, `fel_retrieval`, and `fel_ontology` packages.

## Test

```sh
.venv/bin/pytest apps/api/tests
```

Database-backed tests skip unless `TEST_DATABASE_URL` points at a migrated
PostgreSQL database; with `FEL_REQUIRE_DB=1` (as CI sets it) a missing URL is
an error instead. See [Testing guide](../../docs/development/testing.md#database-backed-tests).

## Route groups

All routes except `/health` are under `/v1` and require a bearer token.

| Group      | Module                 | Paths (examples)                                                                                                         |
| ---------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Workspaces | `app/workspaces.py`    | `POST/GET /v1/workspaces`, `GET/PATCH /v1/workspaces/{workspace_id}`                                                     |
| Corpus     | `app/corpus.py`        | `/v1/entities/{entity_id}/documents`, `/v1/document-versions/resolve`, `/v1/documents/{document_id}`, `/v1/source-spans/{source_span_id}` |
| Reader     | `app/reader.py`        | `GET /v1/documents/{document_id}/reader`                                                                                 |
| Retrieval  | `app/retrieval.py`     | `POST /v1/workspaces/{workspace_id}/queries`, `/v1/queries/{query_id}/reruns`, `/v1/retrieval-runs/{run_id}` and its `events`, `event-history`, `feedback` |
| Extraction | `app/extraction/`      | `/v1/workspaces/{workspaceId}/extraction-runs`, `/v1/extraction-runs/{runId}`, `/v1/extractions/review`, `/v1/approved-extractions/{recordId}` and versions/corrections |

The machine-readable contract is the OpenAPI description in
[`packages/contracts`](../../packages/contracts/).

## Authentication and deployment guard

`FEL_AUTH_MODE` selects the verifier: `mock` (default; unsigned development
tokens) or `supabase` (asymmetric signature verification against
`FEL_AUTH_ISSUER` / `FEL_AUTH_AUDIENCE`). The token establishes identity only;
the role always comes from the `memberships` table.

Before any verifier runs, `app/deployment.py` checks `FEL_DEPLOYMENT_MODE`
(default `public`). `public` requires `supabase` auth. `reader-smoke` and
`synthetic-http` require `mock` auth plus a matching target marker file in
`FEL_STORAGE_DIR`; `synthetic-http` also requires `FEL_ALLOW_MOCK_LLM=1` and a
loopback database host. Any other combination returns 503 `AUTH_UNAVAILABLE`.

## Configuration

Read by `app/config.py` unless noted.

| Variable                                                  | Default         | Purpose                                         |
| --------------------------------------------------------- | --------------- | ----------------------------------------------- |
| `FEL_DATABASE_URL`                                        | none            | PostgreSQL connection URL                       |
| `FEL_STORAGE_DIR`                                         | none            | Canonical evidence objects; deployment markers  |
| `FEL_DEPLOYMENT_MODE`                                     | `public`        | Deployment guard mode                           |
| `FEL_READER_SMOKE_TARGET`, `FEL_SYNTHETIC_HTTP_TARGET`    | empty           | Expected marker targets for the smoke modes     |
| `FEL_AUTH_MODE`                                           | `mock`          | `mock` or `supabase`                            |
| `FEL_AUTH_ISSUER`, `FEL_AUTH_AUDIENCE`                    | empty, `authenticated` | Supabase verifier settings               |
| `FEL_ALLOW_MOCK_LLM`                                      | empty           | Required (`1`) for `synthetic-http`             |
| `FEL_USER_DAILY_LIMIT_USD`, `FEL_ORG_MONTHLY_LIMIT_USD`   | `25`, `1000`    | Hard cost limits                                |
| `FEL_USER_DAILY_SOFT_USD`, `FEL_ORG_MONTHLY_SOFT_USD`     | `10`, `500`     | Soft cost limits                                |
| `FEL_RESEARCH_QUERY_COST_USD`                             | `0.25`          | Per-query reservation charged before execution  |
| `FEL_COST_PER_1K_INPUT_USD`, `FEL_COST_PER_1K_OUTPUT_USD` | `0.005`, `0.015`| Placeholder token pricing for metering          |
| `FEL_RATE_LIMIT_QPS`, `FEL_RATE_LIMIT_BURST`              | `5`, `20`       | In-process rate limiter; `0` qps disables it    |
| `FEL_DB_POOL_MIN`, `FEL_DB_POOL_MAX`                      | `1`, `10`       | Connection pool size                            |
| `FEL_SENTRY_DSN`                                          | none            | Error reporting (`app/observability.py`)        |

## Related pages

- [API hardening and compatibility](HARDENING.md) — pagination, reader and trace bounds
- [Extraction HTTP load acceptance](EXTRACTION_LOAD.md) — opt-in load benchmark
- [API performance checks](PERFORMANCE.md) — opt-in query p95 benchmark
- [Workers](../../workers/README.md) — the job consumer that shares this database
- [Architecture overview](../../docs/architecture/overview.md)
- [System design](../../docs/architecture/system-design.md)
- [Local development](../../docs/development/local.md)
