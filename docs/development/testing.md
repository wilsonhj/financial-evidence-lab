# Testing guide

Financial Evidence Lab tests correctness at several boundaries: pure domain
logic, generated contracts, service adapters, PostgreSQL/RLS behavior,
cross-stack fixtures, browser flows, migrations, and security advisories.

The fastest useful command depends on what you changed. Run the smallest
relevant loop while developing, then the full gate before review.

## Test matrix

| Layer                     | Main tools                                            | Covers                                                                |
| ------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------- |
| TypeScript unit/component | Vitest, Testing Library                               | contracts, web state, reader rendering, observatory behavior          |
| Python unit               | pytest                                                | API services, worker logic, provider mocks, retrieval, graders        |
| Database integration      | pytest + PostgreSQL/pgvector                          | migrations, RLS, queues, reader snapshots, retrieval persistence      |
| Contract drift            | repository generation scripts                         | JSON Schema/OpenAPI ↔ generated TypeScript consistency                |
| Browser                   | Playwright                                            | fixture-mode Next.js routes and core interactions                     |
| Migration/operations      | migration applier + SQL harnesses + PostgreSQL        | clean apply, ledger/checksum drift, role/RLS behavior, backup/restore |
| Static quality            | ESLint, TypeScript, Ruff, mypy, Prettier, Black       | syntax, types, style, import and API mistakes                         |
| Security                  | Gitleaks, Bandit, pip-audit, bulk npm advisory script | secrets, static Python findings, dependency advisories                |

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

# Focused packages — all eight of pyproject.toml's testpaths
.venv/bin/pytest apps/api/tests
.venv/bin/pytest workers/tests
.venv/bin/pytest packages/retrieval/tests
.venv/bin/pytest packages/retrieval-evals/tests
.venv/bin/pytest packages/ontology/tests
.venv/bin/pytest packages/providers/tests
.venv/bin/pytest evals/tests
.venv/bin/pytest scripts/db/tests

# Static checks (matches the Makefile's format-check/lint/typecheck targets
# and ci.yml's python job exactly — packages/ontology joined the tree in #145)
.venv/bin/ruff check \
  apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology \
  scripts conftest.py
.venv/bin/mypy \
  apps/api/app workers/src evals/graders \
  packages/providers/fel_providers \
  packages/retrieval/fel_retrieval \
  packages/retrieval-evals/fel_retrieval_evals \
  packages/ontology/fel_ontology
.venv/bin/black --check \
  apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology \
  scripts conftest.py

# Security gates. CI runs these too — bandit and pip-audit in ci.yml's python
# job, audit-bulk in its javascript job. They are the three gate commands most
# often missed locally, because the sections above stop at the static checks.
.venv/bin/bandit -q -r \
  apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology \
  scripts -c pyproject.toml
.venv/bin/pip-audit -r requirements.txt
.venv/bin/pip-audit -r requirements-dev.txt
node scripts/audit-bulk.mjs
```

## Database-backed tests

Create a dedicated PostgreSQL database with pgvector and apply every migration.

If PostgreSQL is a native install reachable over its default Unix socket,
the bare form works:

```sh
createdb fel_test
export TEST_DATABASE_URL=postgresql:///fel_test
.venv/bin/python scripts/db/migrate.py
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
export TEST_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_test
.venv/bin/python scripts/db/migrate.py
.venv/bin/pytest
```

Requirements:

- the test URL must never point to production;
- the database must support pgvector;
- the role must be able to run the repository's migration/setup fixtures;
- retrieval isolation tests may create disposable sibling databases, so the
  role used for the full suite needs `CREATEDB`.

`scripts/db/migrate.py` applies pending migrations and records each one, with
its sha256, in a `schema_migrations` ledger; re-running is a no-op, `--check`
fails when anything is pending or when an applied file was edited, and
`--baseline` adopts a database that an earlier shell loop already migrated.
[`local.md`](./local.md#option-b-local-postgresql-and-api) documents the flags
and exit codes. `make db-migrate` and `make db-check` are the shorthands.

### Failing when DB-gated suites skip

When `TEST_DATABASE_URL` is absent, DB-gated suites intentionally skip. A green
local run with skips is not equivalent to the GitHub Actions PostgreSQL jobs.

Every run therefore ends with a one-line census, e.g.

```
database-gated tests skipped: 187 across 24 module(s) (no TEST_DATABASE_URL)
```

and setting `FEL_REQUIRE_DB_TESTS=1` turns any such skip into a failed session,
listing the modules that skipped:

```sh
FEL_REQUIRE_DB_TESTS=1 TEST_DATABASE_URL=postgresql:///fel_test .venv/bin/pytest
```

CI's `python` job sets `FEL_REQUIRE_DB_TESTS: "1"`, because that job provisions
a Postgres service precisely so nothing skips for want of a database — a
misconfigured service now fails the job instead of quietly halving the suite.
Leave the variable unset on a database-free laptop. The root `conftest.py`
implements this and counts a skip when its reason names `TEST_DATABASE_URL`, so
keep that string in any new gate's skip reason.

The database suites are where tenant isolation, application-role grants,
cutoff boundaries, queue leasing, index immutability, reader snapshot
consistency, and migration behavior are verified. Do not replace them with
repository mocks for schema or RLS changes.

## Coverage floors

Both suites enforce a floor set at the measured baseline minus one point.
A change that drops coverage below the floor fails the run; when coverage
rises, raise the floor rather than leaving slack.

| Suite      | Where                                            | Floor                                                          |
| ---------- | ------------------------------------------------ | -------------------------------------------------------------- |
| Python     | `[tool.coverage.*]` in `pyproject.toml`          | 91% of lines                                                   |
| TypeScript | `test.coverage.thresholds` in `vitest.config.ts` | 87.7% statements, 78.6% branches, 91.2% functions, 89.3% lines |

Python coverage is opt-in so that local iteration stays fast — `pytest` alone
measures nothing, and CI's `python` job runs `pytest --cov --cov-report=term`.
Measure it the way CI does, with a database attached (an un-migrated or absent
database skips a fifth of the suite and understates coverage):

```sh
TEST_DATABASE_URL=postgresql:///fel_test .venv/bin/pytest --cov --cov-report=term
```

JavaScript coverage is on by default (`@vitest/coverage-v8`), so plain
`corepack pnpm run test` — the command CI runs — enforces the thresholds. Only
files the suites actually load are measured.

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

Each figure below records the commit it was measured at. If your run
disagrees, compare SHAs first — a different SHA means the number is merely
stale, the same SHA means one of the two runs is wrong.

Measured on `main` at `a25bf7c` (#152, the handoff reconciliation commit):

- 31 JavaScript/TypeScript test files and 258 tests passed
  (`corepack pnpm run test`).
- 881 Python tests passed and 187 database-gated tests skipped without
  `TEST_DATABASE_URL` (`.venv/bin/pytest`). Every skip in that run is gated on
  `TEST_DATABASE_URL`; nothing skips for any other reason.
- 1068 Python tests collected in total — the 881 above plus the 187 a database
  unlocks.
- `main`'s CI run for that commit had all five jobs green — `secrets`,
  `javascript`, `web-e2e`, `python`, `database`
  (`gh run view --json conclusion,jobs`).

The full-database pass count is deliberately **not** published here. Reaching
it needs pgvector >= 0.8.2, because `0003_retrieval_core.sql` uses halfvec and
HNSW and enforces that version at apply time. The environment used for this
pass could not supply it, so the number was not measured and is not quoted.

What was measured at `a25bf7c`, against a plain Postgres 16 with only
`0001_platform_core.sql` and `0002_corpus_core.sql` applied: 1012 passed and
56 errored, every error tracing to `extension "vector" is not available`. That
exercises 131 of the 187 database-gated tests and leaves 56 unexecuted, so
treat it as a floor rather than the full-database figure. CI's `python` job
(`pgvector/pgvector:0.8.5-pg17`) is the run that covers all 187 — take the
full-database result from there, not from this page.

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
