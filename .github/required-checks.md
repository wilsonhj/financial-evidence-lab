# Required status checks for `main`

Branch protection is applied in the GitHub repository settings by the
integration lead; it cannot be expressed in this repository. This file is the
record of what must be configured so a reviewer can verify the settings
against it (issue #203, review #188).

## Settings → Branches → `main`

- Require a pull request before merging; require review from Code Owners
  (`.github/CODEOWNERS`).
- Require status checks to pass before merging, **require branches to be up to
  date**, and select exactly these checks (the job names in
  `.github/workflows/ci.yml`):

| Required check                                     | Workflow job | What it proves                                                                                     |
| -------------------------------------------------- | ------------ | -------------------------------------------------------------------------------------------------- |
| `Secret scan (gitleaks)`                           | `secrets`    | no committed credential                                                                            |
| `JS/TS — format, lint, typecheck, test, audit`     | `javascript` | contract drift test, vitest coverage thresholds, advisory gate                                     |
| `Web — Playwright E2E (fixture mode)`              | `web-e2e`    | reader and Observatory journeys in the browser                                                     |
| `Python — format, lint, typecheck, test, security` | `python`     | strict mypy, full suite with Postgres, `FEL_REQUIRE_DB_TESTS=1`, coverage floor, bandit, pip-audit |
| `DB — migration and backup-restore smoke`          | `database`   | ledger applier from empty, roles + data survive restore, every migration harness ran               |

- Require conversation resolution before merging.
- Do not allow bypassing the above settings; include administrators.
- Require linear history is **not** enabled: review packages merge by squash,
  and the integration branch merges agent worktrees with merge commits.

## Coverage floors (enforced by the checks above, recorded here)

| Suite                    | Floor                                                      | Where                                                |
| ------------------------ | ---------------------------------------------------------- | ---------------------------------------------------- |
| Python (`pytest --cov`)  | 89% lines                                                  | `pyproject.toml` `[tool.coverage.report] fail_under` |
| JS (`vitest --coverage`) | statements 87.7, branches 78.6, functions 91.2, lines 89.3 | `vitest.config.ts` `coverage.thresholds`             |

Raise a floor in the same pull request that raises coverage; never lower one
without an entry in `docs/handoff/STATUS.md`.

## Where the `Claude Approvals` check fits

If the repository enables the Claude Approvals GitHub App, add its check to the
required list as well; a green CI run that the review app withholds is not
mergeable.
