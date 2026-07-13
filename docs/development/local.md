# Local development (T0002)

Direct processes, no Docker. Everything runs mock-first: no credential is
required for any M0 workflow.

## Prerequisites

Node 22 + pnpm (see `.node-version`), Python 3.11 (see `.python-version`),
and a PostgreSQL 16+ you can create disposable databases on (local Postgres
or a hosted Supabase development project).

```sh
make install          # pnpm workspace + Python venv with all tooling
```

## Database

```sh
createdb fel_dev
for f in db/migrations/*.sql; do psql -d fel_dev -f "$f"; done
export FEL_DATABASE_URL=postgresql:///fel_dev
```

## Processes

```sh
# API (FastAPI) — http://localhost:8000/health
.venv/bin/uvicorn app.main:app --app-dir apps/api --reload

# Worker — heartbeat loop; the queue consumer binds to the jobs table
.venv/bin/python -m fel_workers

# Web — framework-agnostic package tests today; the Next.js runtime is
# introduced by M1-EVIDENCE-UI, which owns apps/web
pnpm --filter @fel/web test
```

## Authentication (mock mode)

`FEL_AUTH_MODE=mock` (default). Create a development bearer token:

```sh
.venv/bin/python -c "from app.auth import make_mock_token; \
print(make_mock_token('<org uuid>', '<user uuid>', 'owner'))"
curl -H "Authorization: Bearer <token>" localhost:8000/v1/workspaces
```

The org and an owner membership must exist (insert into `organizations` /
`memberships`). RLS is active on API request paths: the connection runs as
the non-privileged `fel_app` role with the caller's claims applied per
request, so cross-tenant reads return nothing even in dev.

## Tests and gates

```sh
make ci                                    # full local quality gate
createdb fel_test && for f in db/migrations/*.sql; do psql -d fel_test -f "$f"; done
TEST_DATABASE_URL=postgresql:///fel_test .venv/bin/pytest   # includes RLS/queue suites
```

`TEST_DATABASE_URL`-gated suites skip when the variable is unset; CI
provides a Postgres 17 service container so they always run there.

## Provider mocks

`fel_providers` exposes the frozen interfaces (LLM, embeddings <=512 dims,
storage, market data, SEC, FRED) with deterministic mocks as the default
binding. Live adapters are integration-credentialed work; the env-var names
they will use are listed in `docs/handoff/CREDENTIALS.md` — never commit
values.
