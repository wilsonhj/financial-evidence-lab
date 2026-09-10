# Measured quality gates

Issue #203 adds regression floors to the existing required Python and JavaScript
jobs. These are measured coverage baselines, not proof of financial accuracy or
live release acceptance. Source inclusion is explicit so unimported production
files count as uncovered. Python excludes tests; JavaScript excludes tests,
test-support utilities, declarations and generated types. Do not lower a floor
or broaden exclusions merely to make a change pass.

## Baseline and floors

Measured September 10, 2026 on Python 3.11.16, Node 24.20.0 and PostgreSQL 17,
after merging #219, #153 and #266 (main `54cad9a`). Exact locked dependencies
and report artifacts accompany PR #269. The initial floors are the measured
baseline minus one percentage point, rounded down to two decimals.

| Metric | Measured | Required |
| --- | ---: | ---: |
| Python combined statement/branch coverage | 89.4177% | 88.41% |
| JavaScript statements | 86.08% | 85.08% |
| JavaScript branches | 77.15% | 76.15% |
| JavaScript functions | 83.89% | 82.89% |
| JavaScript lines | 87.33% | 86.33% |

Python measured 9,961 covered statements out of 10,867 and 2,739 covered branches
out of 3,336: 12,700 / 14,203 combined. All 1,778 tests passed; three opt-in
performance measurements are intentionally separate. PostgreSQL suites ran
with `FEL_REQUIRE_DB=1`; their absence cannot produce this acceptance evidence.
JavaScript measured all 50 test files with production source inclusion.

Run the same gates locally from the repository root:

```sh
TEST_DATABASE_URL=... FEL_REQUIRE_DB=1 python -m pytest --cov --cov-report=term-missing --cov-report=json:coverage/python.json
pnpm run test --coverage
```

Use an isolated migrated test database, never a deployed database. Python reads
its floor from `pyproject.toml`; Vitest reads all four from `vitest.config.ts`.
Targeted developer tests can omit `--cov`. CI uploads coverage JSON even when a
floor fails. A deliberate selected-test-only run passed its tests but failed
the committed coverage floors in both runtimes, proving the gates reject lost
coverage. Raise floors through a reviewed measured change as coverage improves.

## Browser cache and diagnostics

The Chromium cache key includes runner OS, architecture and the installed
Playwright version. Browser binaries download on a cache miss; OS dependencies
install on every run. Playwright cautions that restoring binaries may take as
long as downloading them, so this is the issue's requested cache mechanism,
not a measured speed claim. See the [official guidance](https://playwright.dev/docs/ci#caching-browsers).

CI permits one retry; local runs retain zero. The first retry records a trace,
and `playwright-results` artifacts retain test results for inspection, including
flaky successes. Fixture mode remains isolated from the live backend/providers.

## Sentry runtime

The hashed runtime closure now includes `sentry-sdk[fastapi]` 2.69.1. Both API
and worker initialization remain conditional on `FEL_SENTRY_DSN`; unset means no
SDK initialization. Both disable default PII, frame locals and request bodies.
Worker performance tracing defaults to zero. Tests use synthetic DSNs and fake
or in-memory transports, with no external events sent. A custom installation
missing the SDK still warns instead of crashing when a DSN is configured.

These controls exclude automatic request/body/local-variable fields; they do
not promise to remove financial text someone puts directly in exception text
or an explicit event. Approved hosted telemetry and the second real reviewer
remain separately recorded acceptance under #203.

## Repository enforcement

The exact seven required check names and application status are recorded in
[the required-checks manifest](../../.github/required-checks.md). A committed
manifest alone does not protect a branch. Apply and read back the GitHub settings
once the implementation passes review and CI; never claim configured protection
from this document alone. Existing CODEOWNERS remains unchanged pending an
identified additional reviewer with repository access.
