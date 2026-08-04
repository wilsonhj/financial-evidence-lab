# Testing guide

Financial Evidence Lab tests correctness at several boundaries: pure domain
logic, generated contracts, service adapters, PostgreSQL/RLS behavior,
cross-stack fixtures, browser flows, migrations, and security advisories.

The fastest useful command depends on what you changed. Run the smallest
relevant loop while developing, then the full gate before review.

## Test matrix

| Layer                     | Main tools                                            | Covers                                                           |
| ------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| TypeScript unit/component | Vitest, Testing Library                               | contracts, web state, reader rendering, observatory behavior     |
| Python unit               | pytest                                                | API services, worker logic, provider mocks, retrieval, graders   |
| Database integration      | pytest + PostgreSQL/pgvector                          | migrations, RLS, queues, reader snapshots, retrieval persistence |
| Contract drift            | repository generation scripts                         | JSON Schema/OpenAPI ↔ generated TypeScript consistency           |
| Browser                   | Playwright                                            | fixture-mode Next.js routes and core interactions                |
| Migration/operations      | shell harness + PostgreSQL                            | clean apply, role/RLS behavior, backup/restore expectations      |
| Static quality            | ESLint, TypeScript, Ruff, mypy, Prettier, Black       | syntax, types, style, import and API mistakes                    |
| Security                  | Gitleaks, Bandit, pip-audit, bulk npm advisory script | secrets, static Python findings, dependency advisories           |

## Install the exact toolchain

```sh
corepack enable
corepack pnpm install --frozen-lockfile

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

Use `corepack pnpm`, especially when a globally installed pnpm has a different
major version.

If `python3.11 -m venv .venv` fails with `command not found: python3.11`, see
[local.md's `python3.11` is not installed](./local.md#python311-is-not-installed)
— do not substitute a newer local Python; `.python-version` stays pinned to
3.11 because CI builds against it.

## Fast developer loops

### JavaScript and TypeScript

```sh
# All workspace unit/component tests
corepack pnpm run test

# Web only — run from the repo root, not via --filter: the root vitest
# config's `include` globs are repo-root-relative, and `--filter` changes
# cwd to apps/web, so `corepack pnpm --filter @fel/web test` reports "No
# test files found" (exit 1) despite dozens of real test files.
corepack pnpm exec vitest run apps/web

# Type and lint checks
corepack pnpm run typecheck
corepack pnpm run lint
corepack pnpm run format:check
```

Vitest uses the root workspace configuration. Prefer a focused path or test
name while iterating, but run the workspace command before handoff.

### Python

```sh
# All tests; DB-gated suites skip without TEST_DATABASE_URL
.venv/bin/pytest

# Focused packages — all seven of pyproject.toml's testpaths
.venv/bin/pytest apps/api/tests
.venv/bin/pytest workers/tests
.venv/bin/pytest packages/retrieval/tests
.venv/bin/pytest packages/retrieval-evals/tests
.venv/bin/pytest packages/ontology/tests
.venv/bin/pytest packages/providers/tests
.venv/bin/pytest evals/tests

# Static checks (matches the Makefile's format-check/lint/typecheck targets
# and ci.yml's python job exactly — packages/ontology joined the tree in #145)
.venv/bin/ruff check \
  apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology
.venv/bin/mypy \
  apps/api/app workers/src evals/graders \
  packages/providers/fel_providers \
  packages/retrieval/fel_retrieval \
  packages/retrieval-evals/fel_retrieval_evals \
  packages/ontology/fel_ontology
.venv/bin/black --check \
  apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology

# Security gates. CI runs these too — bandit and pip-audit in ci.yml's python
# job, audit-bulk in its javascript job. They are the three gate commands most
# often missed locally, because the sections above stop at the static checks.
.venv/bin/bandit -q -r \
  apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology \
  -c pyproject.toml
.venv/bin/pip-audit -r requirements-dev.txt
node scripts/audit-bulk.mjs
```

## Database-backed tests

Create a dedicated PostgreSQL database with pgvector and apply every migration.

If PostgreSQL is a native install reachable over its default Unix socket,
the bare form works:

```sh
createdb fel_test
for migration in db/migrations/*.sql; do
  psql postgresql:///fel_test -v ON_ERROR_STOP=1 -f "$migration"
done
export TEST_DATABASE_URL=postgresql:///fel_test
.venv/bin/pytest
```

If you started PostgreSQL with
[`local.md`'s Docker option](./local.md#option-b-local-postgresql-and-api),
it only listens over TCP on `localhost:5432` — the bare form above fails
with `connection to server on socket "/tmp/.s.PGSQL.5432" failed: No such
file or directory`. Use the same host/port/credentials as
`FEL_DATABASE_URL` instead:

```sh
PGPASSWORD=fel createdb -h localhost -p 5432 -U fel fel_test
for migration in db/migrations/*.sql; do
  psql "postgresql://fel:fel@localhost:5432/fel_test" -v ON_ERROR_STOP=1 -f "$migration"
done
export TEST_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_test
.venv/bin/pytest
```

Requirements:

- the test URL must never point to production;
- the database must support pgvector;
- the role must be able to run the repository's migration/setup fixtures;
- retrieval isolation tests may create disposable sibling databases, so the
  role used for the full suite needs `CREATEDB`.

When `TEST_DATABASE_URL` is absent, DB-gated suites intentionally skip. A green
local run with skips is not equivalent to the GitHub Actions PostgreSQL jobs.

The database suites are where tenant isolation, application-role grants,
cutoff boundaries, queue leasing, index immutability, reader snapshot
consistency, and migration behavior are verified. Do not replace them with
repository mocks for schema or RLS changes.

## Contract generation and drift

Contracts are compatibility surfaces. Generated clients/types must be rebuilt
with the repository scripts and committed with their source contract changes.

Run:

```sh
# Run from the repo root, not via --filter: the root vitest config's `include`
# globs are repo-root-relative, and `--filter` changes cwd to
# packages/contracts, so `corepack pnpm --filter @fel/contracts test` reports
# "No test files found" (exit 1) despite the suite being real.
corepack pnpm exec vitest run packages/contracts
```

Root CI is authoritative. The drift gate is not a separate workflow job: it
runs in-suite as the `generated client drift (check:generated in-suite)` case
in `packages/contracts/contracts.test.ts`, reached through the `javascript`
job's `corepack pnpm run test`. Confirm that case passes.

Contract changes require:

- a `contract-change` issue and any required ADR;
- schema examples for success and typed failures;
- migration compatibility where persistence changes;
- provider/client mock updates;
- tests for old/new boundary behavior.

## Browser tests

Playwright runs the Next.js app in deterministic fixture mode:

```sh
corepack pnpm --filter @fel/web exec playwright install chromium
FEL_EVIDENCE_SOURCE=fixture \
  corepack pnpm --filter @fel/web run test:e2e
```

Use the Playwright report and trace for failures:

```sh
corepack pnpm --filter @fel/web exec playwright show-report
```

Fixture browser tests prove UI behavior, routing, accessibility hooks, and
client/server composition. They do **not** prove PostgreSQL, authentication,
provider, HTTP adapter, or hosted deployment behavior. The production reader
acceptance test must traverse the real worker → database → API → HTTP source →
Next.js path.

## Build verification

The web runtime requires an explicit evidence mode even during build:

```sh
FEL_EVIDENCE_SOURCE=fixture corepack pnpm --filter @fel/web build
```

For HTTP-mode builds, provide all server-side runtime variables described in
[`local.md`](./local.md). Never use a client-public bearer token to make a build
pass.

## Full local gate

After the exact pnpm and Python environments are active:

```sh
make ci
```

The target runs formatting, linting, static types, JS/Python tests, Bandit,
pip-audit, and the bulk npm advisory check. It can require registry/network
access for dependency advisory data.

**Known interaction if you obtained Python 3.11 through `uv`.** The `security`
target's `pip-audit` step builds a disposable venv with
`venv.EnvBuilder(with_pip=True)`, which defaults to `symlinks=False` and so
_copies_ the interpreter binary. `uv`'s standalone CPython builds resolve
`libpython3.11.dylib` through an `@rpath` relative to their original install
location, so the copy cannot load it and the step aborts:

```
Library not loaded: @rpath/libpython3.11.dylib
subprocess.CalledProcessError: ... '-m', 'ensurepip' ... died with <Signals.SIGABRT: 6>
```

This is specific to standalone builds — the same call against a Homebrew or
system 3.11 works. Every other step in `make ci` passes; only `pip-audit` is
affected, and CI is unaffected because GitHub Actions provisions its own
interpreter. Either run the other targets individually
(`make format-check lint typecheck test`) and let CI cover the advisory scan, or
use a non-standalone 3.11 for the audit step.

GitHub Actions additionally runs:

1. Gitleaks;
2. the JS/TS quality and generated-client gates;
3. Playwright browser tests;
4. Python tests with PostgreSQL 17 + pgvector;
5. database migration/backup/restore harnesses.

Treat GitHub Actions as the final repository gate because it exercises services
that a database-free laptop cannot.

## Required tests by change type

| Change               | Minimum evidence                                                                          |
| -------------------- | ----------------------------------------------------------------------------------------- |
| UI component/style   | focused component tests, fixture Playwright path, typecheck/build                         |
| Web data adapter     | unit tests for every typed status; HTTP integration; no fixture fallback                  |
| API route            | auth/validation/error tests plus DB integration for persistence                           |
| RLS or tenancy       | same-tenant positive and cross-tenant negative tests as `fel_app`                         |
| Cutoff/version logic | before, exact-boundary, after, invalid pin, quarantine, direct-read bypass cases          |
| Span/citation logic  | non-first-section global offsets, exact hash slice, corrupt/out-of-range rejection        |
| Queue/worker         | duplicate delivery, concurrent claim, lease expiry, retry/dead-letter, late-write fencing |
| Retrieval            | lane contributions, deterministic fusion, rejection states, replay, schema/DB boundary    |
| Provider adapter     | deterministic mock, timeout/error mapping, redaction, explicit live configuration         |
| Migration            | clean apply, upgrade path, RLS/grants, rollback/restore strategy                          |
| Generated contract   | schema examples, drift check, consumer typecheck                                          |

## Test-data rules

- Use synthetic or license-compatible committed fixtures.
- Pin live evaluation corpora by checksum and record the effective cutoff.
- Never commit provider credentials, personal contact details, or production
  document payloads.
- Deterministic mocks should preserve interface and failure semantics, not
  merely return a happy-path shape.
- A self-validating fixture cannot close a live-provider or cross-stack
  acceptance gate.

## Current baseline

Test counts drift with every PR — the numbers below are illustrative, not a
target to keep in sync. Reproduce them yourself with `corepack pnpm run
test` and `.venv/bin/pytest` before trusting a stale figure; treat GitHub
Actions, not this paragraph, as the source of truth for whether the suite is
green.

Measured on `main` at `61058e4` (#145, M3-EXTRACTION-CORE ontology + worker
FSM — the commit that added `packages/ontology` and the extraction worker):

- 31 JavaScript/TypeScript test files and 258 tests passed
  (`corepack pnpm run test`).
- 861 Python tests passed and 186 database-gated tests skipped without
  `TEST_DATABASE_URL` (`.venv/bin/pytest`).
- 1047 Python tests passed and 0 skipped with `TEST_DATABASE_URL` set against
  a migrated Postgres 17 (`.venv/bin/pytest`).
- `main`'s CI run for that commit had all five jobs green
  (`gh run view --json conclusion,jobs`).

Behavioral gates and zero unresolved high/medium review findings matter more
than maintaining an exact test count.

## Troubleshooting

### HTTP tests fail with a SOCKS/proxy import error

Some developer environments inject proxy variables. Install the environment's
required SOCKS support or run local-only tests with intentionally cleared proxy
variables. Do not clear a required corporate proxy for live provider tests.

### Tests pass locally but DB CI fails

Check:

- all migrations were applied in order;
- local tests ran with `TEST_DATABASE_URL`;
- the test role switched to `fel_app` where production does;
- pgvector version/type behavior matches CI;
- the role has `CREATEDB` for sibling-database isolation tests.

### Playwright cannot start

Install the browser binary, verify port availability, and run the app with
`FEL_EVIDENCE_SOURCE=fixture`. Review `playwright.config.*` before changing
timeouts; a startup/configuration failure is not usually fixed by a longer
assertion timeout.

### Dependency audit fails while unit tests pass

Advisory gates are independent of functional tests. Inspect the exact
transitive dependency and the comments in `pnpm-workspace.yaml`. Shared-path
security overrides must follow the repository governance decision tracked in
issue #141.
