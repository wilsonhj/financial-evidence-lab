# Local development (T0002)

This guide covers three useful setups:

1. **Fixture UI** — fastest onboarding; no database, Python, or credentials.
2. **Local API and database** — exercises authentication, RLS, jobs, and API
   persistence.
3. **HTTP reader stack** — runs Next.js against the real FastAPI composite
   reader endpoint.

Use fixture mode first unless you are changing persistence or cross-service
behavior.

## Prerequisites

| Tool       | Version                  | Used for                                 |
| ---------- | ------------------------ | ---------------------------------------- |
| Node.js    | 22 (`.node-version`)     | Next.js, contracts, and JS/TS tests      |
| pnpm       | 10.33 via Corepack       | Monorepo package management              |
| Python     | 3.11 (`.python-version`) | API, workers, retrieval, and evals       |
| PostgreSQL | 16+ with pgvector        | Persistent API/worker flows and DB tests |

Install repository dependencies:

```sh
corepack enable
corepack pnpm install --frozen-lockfile

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

`requirements.txt` holds the runtime dependencies alone (what the API and
worker images install, and what `infra/railway/*.json` builds with);
`requirements-dev.txt` starts with `-r requirements.txt` and adds the
toolchain. Install the dev file locally — it covers both. There is no hashed
lock file yet; the floors in these files are minimum versions, not pins.

`make install` is a convenience wrapper (it runs `python3 -m venv .venv`, so
it inherits whatever `python3` resolves to); prefer the explicit
`python3.11 -m venv .venv` above and confirm first with `python3 --version`
and `command -v python3.11`. If `python3.11` is missing, see
[`python3.11` is not installed](#python311-is-not-installed) below — do not
substitute `python3.12`/`python3.13` for the venv; `.python-version` stays
pinned to 3.11 because CI builds against it.

## Option A: fixture UI

```sh
FEL_EVIDENCE_SOURCE=fixture corepack pnpm --filter @fel/web dev
```

Open <http://localhost:3000>. The filing reader and Search Observatory use
deterministic fixtures. Fixture mode is intentionally explicit and must not be
used as a silent fallback in a deployed environment.

## Option B: local PostgreSQL and API

### Start PostgreSQL

Any PostgreSQL 16+ instance with pgvector works. If Docker is available, this
is a disposable local option:

```sh
docker run --name fel-postgres \
  -e POSTGRES_USER=fel \
  -e POSTGRES_PASSWORD=fel \
  -e POSTGRES_DB=fel_dev \
  -p 5432:5432 \
  -d pgvector/pgvector:0.8.5-pg17
```

Set the connection URL and apply migrations with the ledger applier:

```sh
export FEL_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_dev
python scripts/db/migrate.py --database-url "$FEL_DATABASE_URL"
```

`make db-migrate` is the same command against `$DATABASE_URL` (falling back to
`$TEST_DATABASE_URL`).

The applier keeps a `schema_migrations` ledger — one row per applied file,
with the file's sha256 — so it replaces the old
`for migration in db/migrations/*.sql; do psql -f ...; done` loop:

| Command                                | Behavior                                                           |
| -------------------------------------- | ------------------------------------------------------------------ |
| `python scripts/db/migrate.py`         | applies pending files in order, each in its own transaction        |
| `python scripts/db/migrate.py --check` | exits non-zero if anything is pending or drifted (`make db-check`) |
| `... --dry-run`                        | prints the plan and changes nothing                                |
| `... --baseline`                       | records every pending file as applied **without running it**       |

It reads `--database-url`, then `$DATABASE_URL`, then `$TEST_DATABASE_URL`,
takes a Postgres advisory lock so two appliers cannot race, and refuses to
proceed when an already-applied file's checksum no longer matches the ledger
(migrations are append-only — correct forward with a new file). Exit codes: 0
success, 1 usage, 2 pending, 3 checksum drift, 4 a migration failed and was
rolled back, 5 could not connect.

**Databases migrated before the ledger existed** — anything set up with the old
shell loop — have the schema but no `schema_migrations` table, so a plain run
would try to re-apply every file. Baseline them once:

```sh
python scripts/db/migrate.py --database-url "$FEL_DATABASE_URL" --baseline
python scripts/db/migrate.py --database-url "$FEL_DATABASE_URL" --check
```

`--baseline` records only files that are not already in the ledger, so it is
safe to run on a database that is partially recorded — but it asserts that the
files really are applied. Never baseline a database that is missing schema.

Migrations create the application roles and enable RLS. The migration user
must be able to create extensions and roles. Application requests later switch
to the non-privileged `fel_app` role inside a transaction.

Reuse this container for [`testing.md`](./testing.md#database-backed-tests)'s
`fel_test` database too: its default recipe assumes a local Unix-socket
install, so a Docker-only setup needs the same `postgresql://fel:fel@localhost:5432/...`
host/port/credentials form instead.

### Seed a development tenant

The API's mock token is not enough by itself: the organization, user, and
membership must exist because database membership is authoritative.

Choose stable development UUIDs:

```sh
export FEL_DEV_ORG_ID=11111111-1111-4111-8111-111111111111
export FEL_DEV_USER_ID=22222222-2222-4222-8222-222222222222
```

Create an organization and its owner membership:

```sh
psql "$FEL_DATABASE_URL" \
  -v org_id="$FEL_DEV_ORG_ID" \
  -v user_id="$FEL_DEV_USER_ID" <<'SQL'
INSERT INTO organizations (id, name)
VALUES (:'org_id', 'Local development')
ON CONFLICT (id) DO NOTHING;

INSERT INTO memberships (org_id, user_id, role)
VALUES (:'org_id', :'user_id', 'owner')
ON CONFLICT (org_id, user_id)
DO UPDATE SET role = EXCLUDED.role;
SQL
```

Keep environment-specific seed SQL outside committed migrations.

### Create a mock bearer token

```sh
export FEL_API_BEARER_TOKEN="$(
  PYTHONPATH=apps/api .venv/bin/python -c \
  "from app.auth import make_mock_token; print(make_mock_token('$FEL_DEV_ORG_ID', '$FEL_DEV_USER_ID', 'owner'))"
)"
```

Mock tokens are a local-development mechanism. Role and membership are looked
up in PostgreSQL; the role embedded in a token is not trusted as authorization.

### Start the API

```sh
export FEL_AUTH_MODE=mock
export FEL_STORAGE_DIR="$PWD/.local/evidence"
mkdir -p "$FEL_STORAGE_DIR"

PYTHONPATH=apps/api:packages/providers:packages/retrieval:packages/ontology:workers/src \
  .venv/bin/uvicorn app.main:app \
  --app-dir apps/api \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

`--app-dir apps/api` only adds `apps/api` to `sys.path`; `app/retrieval.py`
imports the sibling `packages/providers` and `packages/retrieval` packages, so
`uvicorn` fails with `ModuleNotFoundError: No module named 'fel_providers'`
without an explicit `PYTHONPATH`. The value above is the same one the worker
uses below.

In another terminal:

```sh
curl http://localhost:8000/health
curl \
  -H "Authorization: Bearer $FEL_API_BEARER_TOKEN" \
  http://localhost:8000/v1/workspaces
```

`FEL_STORAGE_DIR` holds immutable canonical filing objects. Use a durable,
shared directory whenever the worker and API are separate processes.

## Run the worker

The deployed worker requires exactly one explicit provider mode.

Deterministic smoke mode:

```sh
export FEL_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_dev
export FEL_MOCK_SMOKE=1
unset FEL_SEC_LIVE
PYTHONPATH=apps/api:packages/providers:packages/retrieval:packages/ontology:workers/src \
  .venv/bin/python -m fel_workers run
```

Live SEC mode:

```sh
export FEL_SEC_LIVE=1
unset FEL_MOCK_SMOKE
export FEL_STORAGE_DIR="$PWD/.local/evidence"
export FEL_SEC_USER_AGENT="Financial Evidence Lab developer@example.com"
PYTHONPATH=apps/api:packages/providers:packages/retrieval:packages/ontology:workers/src \
  .venv/bin/python -m fel_workers run
```

`python -m fel_workers` needs the same explicit `PYTHONPATH` as the API above
— `workers/src` for the `fel_workers` package itself (`No module named
fel_workers` without it), and `packages/ontology` for the extraction-queue
import chain the worker loads at startup (`fel_workers.consumer` ->
`fel_workers.extraction` -> `fel_ontology`; `No module named 'fel_ontology'`
without it).

Use a real, monitored contact address in `FEL_SEC_USER_AGENT` and follow the
SEC fair-access policy. Never commit it. The current deployed worker dispatches
SEC discovery/fetch/company-facts jobs. FRED and market adapters exist, but
their live job routing is not yet part of the deployed consumer.

### Extraction worker

`--queue extraction` runs the extraction-job consumer instead of the
ingestion queue above. It requires `FEL_ALLOW_MOCK_LLM=1` to bind the
deterministic mock structured-model — an `extraction` queue with no model
bound fails closed at startup (exit 2), and the reverse (the opt-in on any
other queue) fails closed too. See
[`docs/runbooks/extraction-worker.md`](../runbooks/extraction-worker.md) for
the job payload, budgets, and review semantics; this guide only covers
getting the process running:

```sh
export FEL_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_dev
export FEL_MOCK_SMOKE=1
export FEL_ALLOW_MOCK_LLM=1
unset FEL_SEC_LIVE
PYTHONPATH=apps/api:packages/providers:packages/retrieval:packages/ontology:workers/src \
  .venv/bin/python -m fel_workers run --queue extraction
```

`FEL_ALLOW_MOCK_LLM` answers every `extraction_run` job with a deterministic
mock model that persists FABRICATED proposals to the `needs_review` queue —
non-production only. `FEL_EXTRACTION_MEMORY_STORES=1` additionally redirects
extraction output to in-memory stores that are discarded on exit, for
smoke-testing the pipeline without seeding an `extraction_runs` row; see the
runbook for when that applies.

## Option C: Next.js against the real API

The HTTP source calls the composite reader endpoint from the Next.js server.
It requires one or more entity UUIDs already present in the corpus. There is
no `entities` table to look up directly; entity UUIDs live on ingested rows.
Against a populated `FEL_DATABASE_URL`, find one with:

```sh
psql "$FEL_DATABASE_URL" -c "SELECT DISTINCT entity_id FROM documents ORDER BY entity_id LIMIT 5;"
```

**This returns zero rows if you have only followed the steps above, and that is
not a mistake on your part.** Two things stand between Option B and a populated
corpus, and neither is a step this guide can give you:

1. Nothing here enqueues a job. `python -m fel_workers run` drains the `jobs`
   table and exits; after the Option B steps that table is empty, so the worker
   correctly reports `0 job(s) completed`.
2. Mock mode cannot produce documents even with a job queued.
   `MockSecClient.submissions` (`packages/providers/fel_providers/mocks.py:354`)
   returns an empty `accessionNumber` list for every CIK by design, so discovery
   finds nothing to fetch and `documents` is never written.

Populating the corpus therefore requires live SEC ingestion, which needs the
configured compliant identity and rate limiter — see the `FEL_SEC_LIVE` section
above, and note that casual use is discouraged. If you only want to see the
reader render, use **Option A (fixture mode)**, which needs no database and no
entity ids at all. Option C is for verifying the real HTTP path once you already
have a populated database.

```sh
export FEL_EVIDENCE_SOURCE=http
export FEL_API_BASE_URL=http://localhost:8000
export FEL_API_BEARER_TOKEN="$FEL_API_BEARER_TOKEN"
export FEL_ENTITY_IDS=33333333-3333-4333-8333-333333333333

# Optional point-in-time/version pins:
export FEL_AS_OF=2025-12-31T23:59:59Z
export FEL_CORPUS_VERSION_ID=44444444-4444-4444-8444-444444444444

corepack pnpm --filter @fel/web dev
```

All these variables are server-only. Do not prefix bearer tokens with
`NEXT_PUBLIC_` or import runtime configuration into client components.

The HTTP source fails **closed at request time** when required configuration is
absent — it does not fail at startup. `FEL_EVIDENCE_SOURCE=http` with nothing
else set still reaches "Ready"; the first request then renders an explicit
"Evidence source is not configured" state rather than falling back to fixture
data. The guarantee is that there is no silent fixture fallback in production,
not that the process refuses to boot. In production, non-loopback API URLs must
use HTTPS.

## Useful environment variables

| Variable                       | Service     | Purpose                                                                 |
| ------------------------------ | ----------- | ----------------------------------------------------------------------- |
| `FEL_DATABASE_URL`             | API, worker | PostgreSQL connection URL                                               |
| `FEL_AUTH_MODE`                | API         | `mock` is the only implemented verifier mode                            |
| `FEL_STORAGE_DIR`              | API, worker | Shared canonical evidence-object directory                              |
| `FEL_MOCK_SMOKE`               | Worker      | Explicit deterministic provider mode                                    |
| `FEL_SEC_LIVE`                 | Worker      | Explicit live SEC mode                                                  |
| `FEL_SEC_USER_AGENT`           | Worker      | SEC fair-access identity                                                |
| `FEL_ALLOW_MOCK_LLM`           | Worker      | Explicit opt-in to the mock model on `--queue extraction`               |
| `FEL_EXTRACTION_MEMORY_STORES` | Worker      | Extraction smoke option: output to in-memory stores (discarded on exit) |
| `FEL_EVIDENCE_SOURCE`          | Web         | Exactly `fixture` or `http`                                             |
| `FEL_API_BASE_URL`             | Web         | FastAPI origin in HTTP mode                                             |
| `FEL_API_BEARER_TOKEN`         | Web         | Server-only API token                                                   |
| `FEL_ENTITY_IDS`               | Web         | Comma-separated entity UUIDs                                            |
| `FEL_AS_OF`                    | Web         | Optional RFC 3339 cutoff with explicit offset                           |
| `FEL_CORPUS_VERSION_ID`        | Web         | Optional immutable corpus version UUID                                  |

Cost limits are controlled by `FEL_USER_DAILY_LIMIT_USD`,
`FEL_ORG_MONTHLY_LIMIT_USD`, `FEL_USER_DAILY_SOFT_USD`, and
`FEL_ORG_MONTHLY_SOFT_USD`. Defaults are development-friendly; deployments
should set them deliberately.

## Provider mocks

`fel_providers` exposes the frozen interfaces (LLM, embeddings <=512 dims,
storage, market data, SEC, FRED) with deterministic mocks as the default
binding. Live adapters are integration-credentialed work; the env-var names
they will use are listed in
[`docs/handoff/CREDENTIALS.md`](../handoff/CREDENTIALS.md) — never commit
values. The extraction worker's structured-model mock is a separate,
narrower opt-in (`FEL_ALLOW_MOCK_LLM`, above) — it is not implied by
`FEL_MOCK_SMOKE`.

## Common setup problems

### `python3.11` is not installed

`command -v python3.11` exits 127 on any machine that only ships newer
Python (e.g. one with `python3.12`/`python3.13` but no `3.11`).
`.python-version` stays pinned to 3.11 because CI builds against it — do not
substitute a different local interpreter for the venv.

Get a real 3.11 without installing anything system-wide, using
[uv](https://github.com/astral-sh/uv):

```sh
uv venv --python 3.11 --seed .venv
```

`uv` downloads CPython 3.11 on first use and creates `.venv` with `pip`
already installed (`--seed`), so the rest of this guide's
`.venv/bin/pip install ...` commands work unchanged. pyenv or asdf work too
if you already manage Python versions that way — install/select 3.11 there
and run the `python3.11 -m venv .venv` line above as normal.

### `pnpm` reports the wrong version

Run commands as `corepack pnpm ...` and verify:

```sh
corepack pnpm --version
```

The expected version is the `packageManager` value in `package.json`.

### Database tests skip

Set `TEST_DATABASE_URL` to a migrated PostgreSQL database. Some retrieval tests
create disposable sibling databases, so the test role needs `CREATEDB`. Setting
`FEL_REQUIRE_DB_TESTS=1` turns those skips into a failed run — see
[`testing.md`](./testing.md#database-backed-tests).

### API returns no workspaces with a valid-looking token

Check that the organization and active membership exist. Token claims establish
identity; PostgreSQL membership establishes authorization.

### The reader cannot find canonical content

The API and worker must use the same durable `FEL_STORAGE_DIR`. Database rows
contain immutable object references, not the full canonical filing body.

### Worker exits during startup

Set exactly one of `FEL_MOCK_SMOKE=1` or `FEL_SEC_LIVE=1`. Live SEC mode also
requires `FEL_STORAGE_DIR` and `FEL_SEC_USER_AGENT`; invalid or ambiguous modes
fail closed.

For test commands and CI parity, continue with
[`testing.md`](./testing.md).
