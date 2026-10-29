# Local development

<details>
<summary>Relevant source files</summary>

- [Makefile](../../Makefile) — install, test and CI targets
- [.node-version](../../.node-version) — Node pin
- [.python-version](../../.python-version) — Python pin
- [apps/api/app/config.py](../../apps/api/app/config.py) — API environment variables
- [apps/api/app/auth.py](../../apps/api/app/auth.py) — `make_mock_token` and the mock verifier
- [apps/api/benchmarks/synthetic_target.py](../../apps/api/benchmarks/synthetic_target.py) — `prepare_synthetic_target`
- [workers/src/fel_workers/\_\_main\_\_.py](../../workers/src/fel_workers/__main__.py) — worker modes and startup checks
- [apps/web/src/lib/deployment-mode.ts](../../apps/web/src/lib/deployment-mode.ts) — web deployment and evidence-source modes
- [apps/api/app/deployment.py](../../apps/api/app/deployment.py) — API deployment-mode proof before authentication
- [scripts/db/migrate.py](../../scripts/db/migrate.py) — checksummed migration applier (ADR-0014)
- [db/migrations/](../../db/migrations/) — append-only SQL migrations

</details>

Source references verified against commit `f4b1197`.

This guide covers three useful setups:

1. **Fixture UI** — fastest onboarding; no database, Python, or credentials.
2. **Local API and database** — exercises authentication, RLS, jobs, and API
   persistence.
3. **HTTP reader stack** — runs Next.js against the real FastAPI composite
   reader endpoint.

Use fixture mode first unless you are changing persistence or cross-service
behavior.

## Contents

- [Prerequisites](#prerequisites)
- [Option A: fixture UI](#option-a-fixture-ui)
- [Option B: local PostgreSQL and API](#option-b-local-postgresql-and-api)
- [Run the worker](#run-the-worker)
- [Option C: dedicated HTTP acceptance](#option-c-dedicated-http-acceptance)
- [Useful environment variables](#useful-environment-variables)
- [Provider mocks](#provider-mocks)
- [Common setup problems](#common-setup-problems)
- [Related pages](#related-pages)

## Prerequisites

| Tool       | Version                   | Used for                                |
| ---------- | ------------------------- | --------------------------------------- |
| Node.js    | 24.20.0 (`.node-version`)  | Next.js, contracts, and JS/TS tests       |
| pnpm       | 10.33 via Corepack        | Monorepo package management              |
| Python     | 3.11 (`.python-version`)  | API, workers, retrieval, and evals        |
| PostgreSQL | 16+ with pgvector >= 0.8.2 | Persistent API/worker flows and DB tests  |

With nvm, run `nvm install` once and `nvm use` in the project shell; `.nvmrc`
selects the same exact Node patch as `.node-version`. Keep those pins aligned
when updating Node. The package engine admits only 24.x, and CI reads
`.node-version`. This does not change the machine's default Node version.

For a Node 22 rollback, return to the previous source revision in a separate
checkout, select `nvm use 22.23.2`, and reinstall with
`corepack pnpm install --frozen-lockfile`. Keep pnpm and the dependency lockfile
unchanged; rebuild native dependencies for the selected runtime. If rolling
back an adopted migration branch, revert its runtime-pin commit first.

Hosted web releases must verify the actual Node version in Railway's build
logs. An existing `RAILPACK_NODE_VERSION` variable overrides repository pins;
align it with the selected runtime before a staging release. Local fixture
tests do not establish hosted API/auth/storage readiness. Retain the previous
working web deployment and runtime setting for rollback.

Install repository dependencies:

```sh
corepack enable
corepack pnpm install --frozen-lockfile

make install-py
.venv/bin/pip install --require-hashes -r requirements-dev.lock
```

`make install-py` reads `.python-version` (3.11) and creates `.venv` with
`python3.11`, or with `python3` only when `python3` reports 3.11. Any other
interpreter makes it stop with an error instead of building a venv CI would
not test. It then upgrades pip and installs `requirements-dev.txt`, which lists
minimum versions. The second line installs the exact hashed versions CI uses
(`pip install --require-hashes -r requirements-dev.lock` in
`.github/workflows/ci.yml`). `make install` runs `make install-js` (plain
`pnpm install`) and then `make install-py`.

If `make install-py` reports that Python 3.11 is missing, see
[`python3.11` is not installed](#python311-is-not-installed) below — do not
substitute `python3.12`/`python3.13` for the venv; `.python-version` stays
pinned to 3.11 because CI builds against it.

## Option A: fixture UI

```sh
FEL_DEPLOYMENT_MODE=fixture FEL_API_BEARER_TOKEN= FEL_EVIDENCE_SOURCE=fixture corepack pnpm --filter @fel/web dev
```

Open <http://localhost:3000>. The filing reader and Search Observatory use
deterministic fixtures. Fixture mode is intentionally explicit and must not be
used as a silent fallback in a deployed environment.

## Option B: local PostgreSQL and API

### Start PostgreSQL

Any PostgreSQL 16+ instance with pgvector >= 0.8.2 works;
`db/migrations/0003_retrieval_core.sql` refuses older pgvector versions. If Docker is available, this
is a disposable local option:

```sh
docker run --name fel-postgres \
  -e POSTGRES_USER=fel \
  -e POSTGRES_PASSWORD=fel \
  -e POSTGRES_DB=fel_dev \
  -p 5432:5432 \
  -d pgvector/pgvector:0.8.5-pg17
```

Set the connection URL and apply migrations via the checksummed migration applier (`scripts/db/migrate.py`, ADR-0014):

```sh
export FEL_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_dev
.venv/bin/python scripts/db/migrate.py
```

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
export FEL_DEPLOYMENT_MODE=synthetic-http
export FEL_SYNTHETIC_HTTP_TARGET=local-development
export FEL_AUTH_MODE=mock
export FEL_ALLOW_MOCK_LLM=1
export FEL_STORAGE_DIR="$PWD/.local/evidence"
PYTHONPATH=apps/api .venv/bin/python -c 'import os; from pathlib import Path; from benchmarks.synthetic_target import prepare_synthetic_target; prepare_synthetic_target(os.environ["FEL_DATABASE_URL"], Path(os.environ["FEL_STORAGE_DIR"]), os.environ["FEL_SYNTHETIC_HTTP_TARGET"], "fel_dev")'

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

The worker requires exactly one explicit provider mode: `FEL_SEC_LIVE`,
`FEL_MOCK_SMOKE` or `FEL_FIXTURE_INGEST`. `FEL_FIXTURE_INGEST` runs pinned local
SEC bytes through the real ingestion pipeline and also requires
`FEL_FIXTURE_DIR` and `FEL_STORAGE_DIR`; it is for isolated acceptance runs
only. Each flag accepts `1`, `true`, `yes` or `on`; any other non-empty value
exits with status 2.

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

## Option C: dedicated HTTP acceptance

The public web default deliberately returns 503 until per-user sessions exist.
A deployment bearer is no longer a way to serve an ordinary public reader.
Use fixture UI for normal offline development, or a dedicated synthetic workflow
for actual API/browser integration. Never switch a real user's deployment to a
smoke mode to bypass the guard.

For local reader acceptance, allocate a new migrated empty evidence database and
empty storage directory; keep its DSN in FEL_DATABASE_URL without printing it.
Then select the explicit target and run the existing worker/browser harness:

```sh
export FEL_DEPLOYMENT_MODE=reader-smoke
export FEL_AUTH_MODE=mock
export FEL_READER_SMOKE_TARGET=local-reader
export FEL_STORAGE_DIR="$PWD/.local/reader-smoke"
export READER_SMOKE_MANIFEST="$PWD/.local/reader-manifest.json"
export FEL_ACCEPTANCE_PYTHON="$PWD/.venv/bin/python"
export PYTHONPATH=.:apps/api:workers/src:packages/providers:packages/ontology:packages/retrieval:packages/retrieval-evals
.venv/bin/python -m evals.harness.reader_prod_smoke setup --manifest "$READER_SMOKE_MANIFEST" --dedicated-target "$FEL_READER_SMOKE_TARGET"
corepack pnpm --filter @fel/web exec playwright test --config playwright.reader-prod-smoke.config.ts
```

The setup creates the dedicated storage marker and real immutable fixture data.
Playwright propagates mode/target to its API and all reader variants. Hosted
acceptance has additional protected target/revision checks in the reader-smoke
report README; local tests do not prove hosted readiness.

Extraction cross-stack uses synthetic-http, an explicit FEL_SYNTHETIC_HTTP_TARGET,
local `fel_extraction_acceptance*` database and the canonical `CROSS_STACK_MANIFEST`
emitted by its seeder. Load acceptance retains its local fel_load* database rule;
set the same explicit mode/target and use fresh empty storage so its runner can
create the matching marker. Existing nonempty unmarked storage is never adopted.
See the extraction acceptance workflow and apps/api/EXTRACTION_LOAD.md for their
unchanged workloads and thresholds. These synthetic modes cannot authorize live
provider calls or replace public Supabase identity.

## Useful environment variables

Every `FEL_*` variable below is read from the process environment; none has a
committed `.env` file. "Unset" in the default column means the code has no
fallback value. Never commit real values.

### Deployment and authentication

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `FEL_DEPLOYMENT_MODE` | API, web | API: `public`; web: unset | Operator-selected mode: `public`, `fixture` (web only), `reader-smoke` or `synthetic-http`. The API's `public` mode admits authenticated requests only with `FEL_AUTH_MODE=supabase`, so local mock-token work needs `reader-smoke` or `synthetic-http`; otherwise those requests get 503 `AUTH_UNAVAILABLE` (`apps/api/app/deployment.py`). The web app's guarded routes return 503 unless the mode is `fixture`, `reader-smoke` or `synthetic-http` and that mode's checks pass (`apps/web/src/lib/deployment-mode.ts`). |
| `FEL_AUTH_MODE` | API, web | API: `mock`; web: unset | `mock` or `supabase` (JWKS verification, ADR-0025). The web `reader-smoke` and `synthetic-http` modes require `mock`. |
| `FEL_AUTH_ISSUER` | API | empty | Supabase issuer whose JWKS verifies tokens in `supabase` mode |
| `FEL_AUTH_AUDIENCE` | API | `authenticated` | Expected token audience in `supabase` mode |
| `FEL_READER_SMOKE_TARGET` | API, web, eval harness | empty | Dedicated target name for `reader-smoke`; must match the storage marker |
| `FEL_SYNTHETIC_HTTP_TARGET` | API, web | empty | Dedicated target name for `synthetic-http`; must match the storage marker |
| `CROSS_STACK_MANIFEST` | Web, Playwright cross-stack config | unset | Path to the seeder's manifest; required by web `synthetic-http` mode |
| `FEL_ALLOW_MOCK_LLM` | API, worker, web | unset | Must be `1` for `synthetic-http`; on the worker, opts `--queue extraction` into the mock model |

### Database and storage

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `FEL_DATABASE_URL` | API, worker, `scripts/db/migrate.py` | unset | PostgreSQL connection URL. `migrate.py` falls back to `DATABASE_URL`, then `TEST_DATABASE_URL`. |
| `FEL_DB_POOL_MIN` | API | `1` | Minimum connection-pool size |
| `FEL_DB_POOL_MAX` | API | `10` | Maximum connection-pool size |
| `FEL_STORAGE_DIR` | API, worker | unset | Shared canonical evidence-object directory |
| `FEL_WORKER_DB_ROLE` | Worker | unset | `SET ROLE` after connect (for example `fel_worker`, ADR-0013); unset keeps the login role |

### Worker

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `FEL_MOCK_SMOKE` | Worker | unset | Deterministic provider mode |
| `FEL_SEC_LIVE` | Worker | unset | Live SEC mode; needs `FEL_STORAGE_DIR` and `FEL_SEC_USER_AGENT` |
| `FEL_FIXTURE_INGEST` | Worker | unset | Pinned local SEC bytes through the real pipeline; needs `FEL_FIXTURE_DIR` and `FEL_STORAGE_DIR` |
| `FEL_FIXTURE_DIR` | Worker | unset | Fixture manifest and assets for `FEL_FIXTURE_INGEST` |
| `FEL_SEC_USER_AGENT` | Worker, corpus QA harness | unset | SEC fair-access identity with a monitored contact |
| `FEL_EXTRACTION_MEMORY_STORES` | Worker | unset | Extraction smoke option: output to in-memory stores (discarded on exit) |
| `FEL_WORKER_HEALTH_PORT` | Worker | unset (falls back to `PORT`) | Port for `GET /health`; no socket opens when both are unset |

### Web

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `FEL_EVIDENCE_SOURCE` | Web | unset | Exactly `fixture` or `http`; unset is a configuration error |
| `FEL_API_BASE_URL` | Web | unset | FastAPI origin in HTTP mode |
| `FEL_API_BEARER_TOKEN` | Web | unset | Server-only API token; must be empty in `fixture` mode |
| `FEL_ENTITY_IDS` | Web | unset | Comma-separated entity UUIDs |
| `FEL_WORKSPACE_ID` | Web | unset | Workspace UUID for the HTTP-mode Search Observatory and the extraction pages, which share the Observatory runtime config |
| `FEL_AS_OF` | Web | unset | Optional RFC 3339 cutoff with explicit offset |
| `FEL_CORPUS_VERSION_ID` | Web | unset | Optional immutable corpus version UUID |
| `FEL_WEB_TELEMETRY` | Web | unset | `1` enables the `/api/telemetry` route (404 otherwise); the browser side reads `NEXT_PUBLIC_FEL_WEB_TELEMETRY` at build time |

### Limits and telemetry

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `FEL_USER_DAILY_LIMIT_USD` | API | `25` | Per-user daily hard cost limit |
| `FEL_ORG_MONTHLY_LIMIT_USD` | API | `1000` | Per-organization monthly hard cost limit |
| `FEL_USER_DAILY_SOFT_USD` | API | `10` | Per-user daily soft (warning) limit |
| `FEL_ORG_MONTHLY_SOFT_USD` | API | `500` | Per-organization monthly soft (warning) limit |
| `FEL_RESEARCH_QUERY_COST_USD` | API | `0.25` | Cost charged against the limits before a research query runs |
| `FEL_RATE_LIMIT_QPS` | API | `5` | In-process rate limit; `0` disables the limiter |
| `FEL_RATE_LIMIT_BURST` | API | `20` | Rate-limiter burst size |
| `FEL_SENTRY_DSN` | API, worker | unset | Enables Sentry with PII collection off; unset means no SDK initialization |
| `FEL_SENTRY_TRACES_SAMPLE_RATE` | Worker | `0` | Worker performance-trace sample rate |

The cost defaults are development-friendly; deployments should set them
deliberately. `FEL_COST_PER_1K_INPUT_USD` and `FEL_COST_PER_1K_OUTPUT_USD`
(API) hold placeholder token pricing for metering.

### Tests

| Variable | Read by | Default | Purpose |
| --- | --- | --- | --- |
| `TEST_DATABASE_URL` | pytest suites, `make eval-retrieval-gate` | unset | Migrated test database; DB-gated suites skip without it |
| `FEL_REQUIRE_DB` | pytest suites | unset | `1` makes a missing `TEST_DATABASE_URL` a collection error instead of skips (CI sets it) |
| `FEL_HARNESS_ALLOW_RESET` | `evals/harness/corpus_qa.py` | unset | `1` marks a database not ending in `_test` as disposable for `--reset-corpus` |
| `FEL_RUN_BENCHMARKS` | calculation-engine benchmark tests | unset | `1` enables opt-in timing assertions |
| `FEL_RUN_QUERY_BENCHMARK` | `apps/api/tests/test_retrieval_api.py` | unset | `1` runs the opt-in query p95 benchmark on a controlled host |
| `FEL_QUERY_BENCHMARK_PROFILE` | `apps/api/tests/test_retrieval_api.py` | unset | Required with the benchmark: describes the controlled host |
| `FEL_QUERY_BENCHMARK_P95_SECONDS` | `apps/api/tests/test_retrieval_api.py` | unset | Required with the benchmark: the declared p95 latency target in seconds |

Provider credentials (SEC, FRED, market data, LLM, Supabase) are listed by name
in [`docs/handoff/CREDENTIALS.md`](../handoff/CREDENTIALS.md); the acceptance
harness variables (`READER_SMOKE_MANIFEST`, `FEL_ACCEPTANCE_PYTHON`) are set in
[Option C](#option-c-dedicated-http-acceptance).

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
create disposable sibling databases, so the test role needs `CREATEDB`.

### API returns no workspaces with a valid-looking token

Check that the organization and active membership exist. Token claims establish
identity; PostgreSQL membership establishes authorization.

### The reader cannot find canonical content

The API and worker must use the same durable `FEL_STORAGE_DIR`. Database rows
contain immutable object references, not the full canonical filing body.

### Worker exits during startup

Set exactly one of `FEL_MOCK_SMOKE=1`, `FEL_SEC_LIVE=1` or
`FEL_FIXTURE_INGEST=1`. Live SEC mode also requires `FEL_STORAGE_DIR` and
`FEL_SEC_USER_AGENT`; fixture-ingest mode also requires `FEL_FIXTURE_DIR` and
`FEL_STORAGE_DIR`. Invalid or ambiguous modes fail closed.

For test commands and CI parity, continue with
[`testing.md`](./testing.md).

## Related pages

- [Testing guide](testing.md)
- [Measured quality gates](quality-gates.md)
- [API](../../apps/api/README.md)
- [Workers](../../workers/README.md)
- [Extraction worker runbook](../runbooks/extraction-worker.md)
- [Architecture overview](../architecture/overview.md)
