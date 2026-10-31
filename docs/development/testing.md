# Testing guide

<details>
<summary>Relevant source files</summary>

- [pyproject.toml](../../pyproject.toml) — pytest `testpaths`, `pythonpath` and coverage settings
- [vitest.config.ts](../../vitest.config.ts) — root Vitest configuration
- [Makefile](../../Makefile) — `make ci` and its component targets
- [apps/api/tests/conftest.py](../../apps/api/tests/conftest.py) — `TEST_DATABASE_URL` and `FEL_REQUIRE_DB` gating
- [packages/contracts/contracts.test.ts](../../packages/contracts/contracts.test.ts) — generated-client drift check
- [apps/web/playwright.config.ts](../../apps/web/playwright.config.ts) — fixture-mode browser tests
- [.github/workflows/ci.yml](../../.github/workflows/ci.yml) — CI jobs
- [.github/required-checks.md](../../.github/required-checks.md) — the seven required pull-request checks
- [scripts/db/migrate.py](../../scripts/db/migrate.py) — checksummed migration applier (ADR-0014)
- [.github/workflows/advisories.yml](../../.github/workflows/advisories.yml) — scheduled advisory refresh
- [scripts/audit-bulk.mjs](../../scripts/audit-bulk.mjs) — bulk npm advisory check

</details>

Source references verified against commit `f4b1197`.

Financial Evidence Lab tests correctness at several boundaries: pure domain
logic, generated contracts, service adapters, PostgreSQL/RLS behavior,
cross-stack fixtures, browser flows, migrations, and security advisories.

The fastest useful command depends on what you changed. Run the smallest
relevant loop while developing, then the full gate before review.

## Contents

- [Test matrix](#test-matrix)
- [Install the exact toolchain](#install-the-exact-toolchain)
- [Fast developer loops](#fast-developer-loops)
- [Database-backed tests](#database-backed-tests)
- [Contract generation and drift](#contract-generation-and-drift)
- [Browser tests](#browser-tests)
- [Build verification](#build-verification)
- [Full local gate](#full-local-gate)
- [Required tests by change type](#required-tests-by-change-type)
- [Test-data rules](#test-data-rules)
- [Current baseline](#current-baseline)
- [Troubleshooting](#troubleshooting)
- [Related pages](#related-pages)

## Test matrix

| Layer                     | Main tools                                            | Covers                                                           |
| ------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| TypeScript unit/component | Vitest (`node` environment)                           | contracts, web state, reader rendering, observatory behavior     |
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

make install-py
.venv/bin/pip install --require-hashes -r requirements-dev.lock
```

Use `corepack pnpm`, especially when a globally installed pnpm has a different
major version.

`make install-py` reads `.python-version`, creates `.venv` with the matching
interpreter (`python3.11`, or `python3` only when it reports 3.11), and refuses
to run otherwise. It then installs `requirements-dev.txt`, whose entries are
minimum versions. The second line pins the venv to the exact hashed versions
CI installs (`pip install --require-hashes -r requirements-dev.lock` in
ci.yml's `python` job), so run it after `make install-py`.

If `make install-py` reports that Python 3.11 is missing, see
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

# Focused packages — all nine of pyproject.toml's testpaths
.venv/bin/pytest apps/api/tests
.venv/bin/pytest scripts/db/tests
.venv/bin/pytest workers/tests
.venv/bin/pytest packages/retrieval/tests
.venv/bin/pytest packages/retrieval-evals/tests
.venv/bin/pytest packages/ontology/tests
.venv/bin/pytest packages/providers/tests
.venv/bin/pytest evals/tests
.venv/bin/pytest packages/calculation-engine/tests

# Static checks: Black, Ruff and mypy, plus the JS format/lint/typecheck
# scripts. The Makefile owns the path lists; do not copy them here.
make format-check lint typecheck

# Security gates: Bandit, pip-audit and the bulk npm advisory check
make security
```

The Makefile's Black, Ruff and Bandit path lists match ci.yml's `python` job.
Two Python gates differ from CI:

- **mypy:** CI's mypy step also checks `scripts/db`, which `make typecheck`
  does not yet include. Run `.venv/bin/mypy scripts/db` as well when you change
  the migration applier.
- **pip-audit:** `make security` audits `requirements-dev.txt`. CI audits the
  three lock files instead: `requirements.lock`, `requirements-dev.lock` and
  `scripts/runtime/build.lock`.

[Full local gate](#full-local-gate) lists every difference between `make ci`
and CI.

## Database-backed tests

Create a dedicated PostgreSQL database with pgvector >= 0.8.2 and apply every
migration with the checksummed applier (`scripts/db/migrate.py`, ADR-0014). The
applier writes the `schema_migrations` ledger; a `psql` loop over
`db/migrations/*.sql` does not, and
`infra/scripts/backup_restore_smoke.sh` refuses a database without a ledger.

If PostgreSQL is a native install reachable over its default Unix socket,
the bare form works:

```sh
createdb fel_test
export TEST_DATABASE_URL=postgresql:///fel_test
.venv/bin/python scripts/db/migrate.py --database-url "$TEST_DATABASE_URL"
.venv/bin/pytest
```

Pass `--database-url` explicitly. Without it, `migrate.py` uses
`FEL_DATABASE_URL` first, then `DATABASE_URL`, then `TEST_DATABASE_URL`, so a
shell that already exports `FEL_DATABASE_URL` would migrate that database
instead. `migrate.py --check` exits non-zero if a migration is pending or an
applied file changed.

If you started PostgreSQL with
[`local.md`'s Docker option](./local.md#option-b-local-postgresql-and-api),
it only listens over TCP on `localhost:5432` — the bare form above fails
with `connection to server on socket "/tmp/.s.PGSQL.5432" failed: No such
file or directory`. Use the same host/port/credentials as
`FEL_DATABASE_URL` instead:

```sh
PGPASSWORD=fel createdb -h localhost -p 5432 -U fel fel_test
export TEST_DATABASE_URL=postgresql://fel:fel@localhost:5432/fel_test
.venv/bin/python scripts/db/migrate.py --database-url "$TEST_DATABASE_URL"
.venv/bin/pytest
```

Requirements:

- the test URL must never point to production;
- the database must have pgvector >= 0.8.2 (`0003_retrieval_core.sql` refuses
  older versions);
- the role must be able to run the repository's migration/setup fixtures;
- retrieval isolation tests may create disposable sibling databases, so the
  role used for the full suite needs `CREATEDB`.

When `TEST_DATABASE_URL` is absent, DB-gated suites intentionally skip. A green
local run with skips is not equivalent to the GitHub Actions PostgreSQL jobs.
CI sets `FEL_REQUIRE_DB=1`, which turns a missing `TEST_DATABASE_URL` into a
collection error; set it locally to get the same guarantee.

Test-isolation rule: a new DB-backed extraction suite, including any added by
#61 or #62, must run against an isolated `<db>_extraction` sibling database
created by `ensure_extraction_database`
(`workers/tests/extraction/test_postgres_crash_resume.py`), never the shared
`TEST_DATABASE_URL` database. Extraction runs are permanent rows that pin a
`corpus_versions` row, so one committed on the shared database blocks the
`DELETE FROM corpus_versions` cleanup that other suites rely on. The helper
rebuilds a stale sibling against the current schema
([ADR-0011](../decisions/ADR-0011-extraction-step-output-column.md)).

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
corepack pnpm --filter @fel/web run test:e2e
```

`apps/web/playwright.config.ts` starts the server itself with
`FEL_DEPLOYMENT_MODE=fixture`, an empty `FEL_API_BEARER_TOKEN` and
`FEL_EVIDENCE_SOURCE=fixture`, so no variables are needed on the command line.

The config uses the `list` reporter only, so there is no HTML report to open.
Failure output goes to `apps/web/test-results/` (CI uploads that directory as
the `playwright-results` artifact). Traces are recorded on the first retry,
and local runs do not retry. To record one locally, rerun with
`--trace on`:

```sh
corepack pnpm --filter @fel/web exec playwright test --trace on
```

Fixture browser tests prove UI behavior, routing, accessibility hooks, and
client/server composition. They do **not** prove PostgreSQL, authentication,
provider, HTTP adapter, or hosted deployment behavior. The production reader
acceptance test must traverse the real worker → database → API → HTTP source →
Next.js path.

## Build verification

Build with the same variables `apps/web/playwright.config.ts` passes to its
server:

```sh
FEL_DEPLOYMENT_MODE=fixture FEL_API_BEARER_TOKEN= FEL_EVIDENCE_SOURCE=fixture \
  corepack pnpm --filter @fel/web build
```

The guarded routes (`apps/web/src/proxy.ts`) return 503 unless
`FEL_DEPLOYMENT_MODE` is `fixture`, `reader-smoke` or `synthetic-http` and that
mode's checks pass (`apps/web/src/lib/deployment-mode.ts`). Fixture mode also
requires `FEL_EVIDENCE_SOURCE=fixture` and an empty `FEL_API_BEARER_TOKEN`.

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

### Where `make ci` and CI differ

`make ci` is not a full replica of CI. As of `f4b1197`:

| Area | `make ci` | CI (`.github/workflows/ci.yml`) |
| --- | --- | --- |
| Python install | `make install-py` installs `requirements-dev.txt` (minimum versions) | `pip install --require-hashes -r requirements-dev.lock` |
| Coverage floors | `pytest` and `pnpm run test` with no coverage | `pytest --cov ...` and `pnpm run test --coverage`; floors in `pyproject.toml` and `vitest.config.ts` fail the job (see [quality-gates.md](quality-gates.md)) |
| mypy | omits `scripts/db` | also checks `scripts/db` |
| pip-audit | `requirements-dev.txt` | `requirements.lock`, `requirements-dev.lock` and `scripts/runtime/build.lock` |
| Database suites | skip unless you set `TEST_DATABASE_URL` | PostgreSQL 17 + pgvector 0.8.5 service, `FEL_REQUIRE_DB=1` |
| Not run by `make ci` | — | Gitleaks, Playwright (fixture and deployment-guard), the reproducible production install, and the migration/backup-restore smoke |

**Known interaction if you obtained Python 3.11 through `uv`.** The `security`
target's `pip-audit` step builds a disposable venv with
`venv.EnvBuilder(with_pip=True)`, which defaults to `symlinks=False` and so
_copies_ the interpreter binary. `uv`'s standalone CPython builds resolve
`libpython3.11.dylib` through an `@rpath` relative to their original install
location, so the copy cannot load it and the step aborts:

```text
Library not loaded: @rpath/libpython3.11.dylib
subprocess.CalledProcessError: ... '-m', 'ensurepip' ... died with <Signals.SIGABRT: 6>
```

This is specific to standalone builds — the same call against a Homebrew or
system 3.11 works. Every other step in `make ci` passes; only `pip-audit` is
affected, and CI is unaffected because GitHub Actions provisions its own
interpreter. Either run the other targets individually
(`make format-check lint typecheck test`) and let CI cover the advisory scan, or
use a non-standalone 3.11 for the audit step.

Seven checks must pass before a pull request can merge. The exact names are
in [`.github/required-checks.md`](../../.github/required-checks.md):

1. `Secret scan (gitleaks)`;
2. `JS/TS — format, lint, typecheck, test, audit` — includes the
   generated-client drift case and the JavaScript coverage floors;
3. `Web — Playwright E2E (fixture mode)` — the fixture suite, then the public
   deployment-guard suite (`playwright.deployment-guard.config.ts`) over
   production HTTP;
4. `Python — format, lint, typecheck, test, security` — PostgreSQL 17 +
   pgvector and the Python coverage floor;
5. `Python — reproducible production installs` — builds the runtime closure
   twice from `requirements.lock` and `scripts/runtime/build.lock` and diffs
   the results;
6. `DB — migration and backup-restore smoke` — `migrate.py`, backup/restore
   and the migration regression harnesses;
7. `Shared-path changes carry contract-change` (`shared-paths.yml`).

These workflows also run on pull requests but are not required checks:

- `extraction-acceptance.yml` — extraction HTTP API, worker and browser
  acceptance;
- `docs.yml` — offline relative-link and anchor check (lychee) and
  markdownlint on changed Markdown files.

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
- `main`'s CI run for that commit had all five of its jobs green — `secrets`,
  `javascript`, `web-e2e`, `python`, `database`
  (`gh run view --json conclusion,jobs`). That is a historical record; the
  current required set is seven checks, listed under
  [Full local gate](#full-local-gate).

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

Install the browser binary, verify port availability (the fixture config uses
port 3210), and run the app with `FEL_DEPLOYMENT_MODE=fixture`,
`FEL_EVIDENCE_SOURCE=fixture` and an empty `FEL_API_BEARER_TOKEN`. Review `playwright.config.*` before changing
timeouts; a startup/configuration failure is not usually fixed by a longer
assertion timeout.

### Dependency audit fails while unit tests pass

Advisory gates are independent of functional tests. Inspect the exact
transitive dependency and the comments in `pnpm-workspace.yaml`. Shared-path
security overrides must follow the repository governance decision tracked in
issue #141.

### Scheduled dependency-advisory refresh

`.github/workflows/advisories.yml` (#143) runs the same two advisory gates as
`make ci`'s security section on a weekly cron (Monday 06:00 UTC), plus
`workflow_dispatch` for an on-demand run:

- `pnpm install --frozen-lockfile && node scripts/audit-bulk.mjs`
- `pip install -r requirements-dev.txt && pip-audit -r requirements.txt -r requirements-dev.txt`

This exists because PR-triggered CI only re-checks advisories when a PR
touches a dependency file — it does not catch a new advisory published
against an unchanged lockfile. On failure the workflow opens or updates a
single tracking issue titled `Dependency advisories: <date>` (label
`advisory`): it searches for an existing open issue with that label first and
comments on it if found, or creates one otherwise, so a run of consecutive
failures does not spawn a new issue every week.

## Related pages

- [Local development](local.md)
- [Measured quality gates](quality-gates.md)
- [API](../../apps/api/README.md)
- [Workers](../../workers/README.md)
- [System design](../architecture/system-design.md)
