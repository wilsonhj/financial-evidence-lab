# ADR-0032: Reconcile ADR and specification status with the repository

Status: Proposed — for integration-lead acceptance on its PR
Date: 2026-10-31
Occasioned by: #363 (documentation drift remediation, slice S4)
Scope: the editorial corrections listed under "Decision" and nothing else

## Context

Several shared documents no longer describe the repository they sit in. All
evidence below was read at `main` @ `f4b1197` or the PR head.

- ADR-0014 still reads `Status: Proposed`, but its design is fully live:
  `scripts/db/migrate.py`, `make db-migrate` / `make db-check`, the CI
  migration steps (`.github/workflows/ci.yml:185-198`) and both Railway
  `preDeployCommand` entries (`infra/railway/api.json:8`,
  `infra/railway/worker.json:8`). It merged via PR #247 at `75fad38`
  (`docs/handoff/STATUS.md:307`). `CLAUDE.md` requires an accepted ADR for
  migration changes, so a Proposed ADR-0014 leaves every later migration PR
  formally unauthorized.
- ADR-0012's revisit triggers have moved: OpenAI adapters now exist, while the
  only Recall@10 figure was measured on mock embeddings.
- ADR-0005 does not say it was superseded in part, though ADR-0021 (line 16)
  and the index (`docs/decisions/README.md:13`) both say so. ADR-0002 does not
  point to ADR-0012 or ADR-0026. ADR-0001 has no `Date:` line.
- Specs 002 and 003 still say "implementation-ready", and 005 still says
  "Draft for integration-lead ratification", though 005 merged via PR #182 at
  `4e91235` (`docs/handoff/STATUS.md:282`). The 002 and 003 `tasks.md`
  checkboxes are all unchecked and are not maintained. The 002 and 003
  quickstarts name modules, routes and test files that do not exist.
  `specs/001-financial-evidence-lab/plan.md` §1 restates the stack, contrary
  to its own §4 and to `.specify/memory/constitution.md:50`.
- `packages/contracts/README.md` says Python contract tests are still to come;
  `apps/api/tests/test_openapi_parity.py` exists. `db/migrations/README.md`
  calls the directory empty (it holds `0001`-`0011`) and attributes index
  builds to worker paths (no worker or API path builds indexes).
- `make typecheck` (`Makefile:60`) omits `scripts/db`, which CI's mypy step
  (`.github/workflows/ci.yml:129`) includes.

Every one of these paths is shared under `AGENTS.md` "Shared paths". The
`specs/**`, `docs/decisions/**`, `packages/contracts/` and `db/migrations/`
edits fall in the class that needs an accepted ADR, and ADR-0003 requires one
for a standalone `Makefile` edit. This ADR is that authorization, modelled on
ADR-0013.

## Decision

The integration lead authorizes exactly these corrections:

1. **ADR status lines and back-links.**
   - ADR-0014: `Status: Accepted`, effective at PR #247 (`75fad38`). Its
     revisit triggers (a no-transaction migration; more than one schema
     writer) have not fired: the worker service runs only `--check`.
   - ADR-0012: an "Amendment 1 (2026-10-31)" section; Status stays Proposed.
   - ADR-0005: a "Superseded in part (oversized-reader posture) by ADR-0021"
     line under its status.
   - ADR-0002: a "Related decisions" section, appended at the end of the file
     so the `ADR-0002:NN` line citations in ADR-0012 stay valid, naming
     ADR-0012 (Proposed) and ADR-0026.
   - ADR-0001: `Date: 2026-07-12`. Local history is grafted at `10d2ca4`
     (2026-09-13), so local `git log` dates are not evidence. GitHub's history
     shows the file was added by commit `369777f`, PR #2, merged 2026-07-12.
   - `docs/decisions/README.md`: the ADR-0001 date, the ADR-0014 status, and a
     row for this ADR.
2. **Specification status headers and maintenance notes.** Standing status
   lines on `specs/002-*/spec.md`, `specs/003-*/spec.md`,
   `specs/004-*/spec.md` and `specs/005-*/spec.md`, stated against the
   canonical ledger; a one-line note atop `specs/002-*/tasks.md` and
   `specs/003-*/tasks.md` that their checkboxes are not maintained and
   `specs/001-financial-evidence-lab/tasks.md` governs; a new
   `specs/README.md` lifecycle table.
3. **Quickstart and plan path fixes.** `specs/002-*/quickstart.md` and
   `specs/003-*/quickstart.md` name only commands, routes and test files that
   exist. `specs/001-financial-evidence-lab/plan.md` §1 points to ADR-0002 and
   the ADR index instead of restating the stack.
4. **Maintenance notes in shared READMEs.** `packages/contracts/README.md`
   (Python contract tests) and `db/migrations/README.md` (directory contents;
   which code builds indexes).
5. **`Makefile`.** Append `scripts/db` to the `typecheck` mypy path list so it
   matches `.github/workflows/ci.yml:129` exactly.
6. **Lint-only formatting** in files this ADR already touches, so the changed
   files pass the `docs.yml` markdownlint job: a doubled blank line removed in
   `db/migrations/README.md`, a `sh` language tag on one code fence in
   ADR-0012, and a blank line before a list in `specs/004-mvp-completion/spec.md`
   (which moves that file's later lines down by one).

It also records these lead decisions from #363, accepted 2026-10-29:

- **D4.** ADR-0014 is accepted as above. ADR-0012 is amended, not withdrawn:
  the "any live provider is wired" trigger has fired; the Recall@10 trigger
  has not effectively fired; the Arm A / Arm B benchmark remains the
  ratify-or-withdraw event; ADR-0026 governs user-funded inference.
- **D7.** No change to the canonical task ledger. T0214a stays checked.
- **D8.** The integration lead posted the authorization for ADR-0029, ADR-0030
  and ADR-0031 on PR #354 on 2026-10-29. Their existing "Accepted by the
  integration lead on PR #354 (2026-10-27)" status lines stand unedited.

This ADR changes no decision content in any ADR beyond the status, date,
back-link and amendment text above. It changes no contract, schema, migration,
lockfile, authentication boundary or cross-package interface. It changes no
task text, task ID, task ordering or checkbox state in any `tasks.md`.

## Consequences

- Future migration PRs cite an accepted ADR-0014.
- ADR-0012 stays the open gate for any provider substitution; nothing here
  ratifies it.
- `make ci` type-checks the same paths as CI's Python job.
- This ADR creates no standing exception for later `specs/**` or
  `docs/decisions/**` edits; each still needs its own authorization under
  `AGENTS.md`.

## Alternatives rejected

- **Leave ADR-0014 Proposed until a migration PR forces the question.**
  Rejected: it leaves a live, load-bearing design unauthorized.
- **Withdraw ADR-0012.** Rejected: the substitution question it governs is
  still open, and withdrawal would discard the benchmark design.
- **One ADR per correction.** Rejected: none changes a decision, and ADR-0013
  shows a single bounded authorization is enough.

## Verification

The authorization holds only if the PR that adds this ADR:

1. changes no `.sql`, OpenAPI, JSON-schema, lockfile or source file, and
   changes the `Makefile` by exactly the `scripts/db` path;
2. shows `Makefile` `typecheck` and `.github/workflows/ci.yml:129` listing the
   same mypy paths;
3. changes no `- [ ]` / `- [x]` line in any `tasks.md`; and
4. changes ADR text only as listed under "Decision" items 1 and 6.
