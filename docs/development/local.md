# Local development

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

`make install` is a convenience wrapper, but ensure `python3` resolves to
Python 3.11 and `pnpm` resolves through Corepack before using it.

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

Set the connection URL and apply migrations in filename order:

```sh
export FEL_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_dev
for migration in db/migrations/*.sql; do
  psql "$FEL_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
done
```

Migrations create the application roles and enable RLS. The migration user
must be able to create extensions and roles. Application requests later switch
to the non-privileged `fel_app` role inside a transaction.

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

.venv/bin/uvicorn app.main:app \
  --app-dir apps/api \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

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
.venv/bin/python -m fel_workers run
```

Live SEC mode:

```sh
export FEL_SEC_LIVE=1
unset FEL_MOCK_SMOKE
export FEL_STORAGE_DIR="$PWD/.local/evidence"
export FEL_SEC_USER_AGENT="Financial Evidence Lab developer@example.com"
.venv/bin/python -m fel_workers run
```

Use a real, monitored contact address in `FEL_SEC_USER_AGENT` and follow the
SEC fair-access policy. Never commit it. The current deployed worker dispatches
SEC discovery/fetch/company-facts jobs. FRED and market adapters exist, but
their live job routing is not yet part of the deployed consumer.

## Option C: Next.js against the real API

The HTTP source calls the composite reader endpoint from the Next.js server.
It requires one or more entity UUIDs already present in the corpus.

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

The HTTP source fails startup when required configuration is absent. In
production, non-loopback API URLs must use HTTPS.

## Useful environment variables

| Variable                | Service     | Purpose                                       |
| ----------------------- | ----------- | --------------------------------------------- |
| `FEL_DATABASE_URL`      | API, worker | PostgreSQL connection URL                     |
| `FEL_AUTH_MODE`         | API         | `mock` is the only implemented verifier mode  |
| `FEL_STORAGE_DIR`       | API, worker | Shared canonical evidence-object directory    |
| `FEL_MOCK_SMOKE`        | Worker      | Explicit deterministic provider mode          |
| `FEL_SEC_LIVE`          | Worker      | Explicit live SEC mode                        |
| `FEL_SEC_USER_AGENT`    | Worker      | SEC fair-access identity                      |
| `FEL_EVIDENCE_SOURCE`   | Web         | Exactly `fixture` or `http`                   |
| `FEL_API_BASE_URL`      | Web         | FastAPI origin in HTTP mode                   |
| `FEL_API_BEARER_TOKEN`  | Web         | Server-only API token                         |
| `FEL_ENTITY_IDS`        | Web         | Comma-separated entity UUIDs                  |
| `FEL_AS_OF`             | Web         | Optional RFC 3339 cutoff with explicit offset |
| `FEL_CORPUS_VERSION_ID` | Web         | Optional immutable corpus version UUID        |

Cost limits are controlled by `FEL_USER_DAILY_LIMIT_USD`,
`FEL_ORG_MONTHLY_LIMIT_USD`, `FEL_USER_DAILY_SOFT_USD`, and
`FEL_ORG_MONTHLY_SOFT_USD`. Defaults are development-friendly; deployments
should set them deliberately.

## Common setup problems

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

Set exactly one of `FEL_MOCK_SMOKE=1` or `FEL_SEC_LIVE=1`. Live SEC mode also
requires `FEL_STORAGE_DIR` and `FEL_SEC_USER_AGENT`; invalid or ambiguous modes
fail closed.

For test commands and CI parity, continue with
[`testing.md`](./testing.md).
