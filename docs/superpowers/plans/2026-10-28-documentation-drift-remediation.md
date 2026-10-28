# Documentation drift remediation

Status: Draft plan for integration-lead review. Not registered as a workstream
and not authorized for implementation. Decisions D1–D7 below are open.

Baseline: `main` @ `f4b1197` (2026-10-28). Every finding below was read
against that commit. Recheck it against the implementation base before editing.

## Outcome

Bring the repository's documentation back in line with the code, CI and
delivery state on `main`. Then reduce the reading path for resuming agents.
This plan changes documentation only, apart from the optional one-line
`Makefile` fix in D5. It does not change behavior, contracts, migrations or
the canonical task ledger's task text.

## Requirements owner and authority

- Requirements come from four read-only audits run on 2026-10-28, plus a
  mechanical link and index check. Their findings are listed per slice below.
  The audits were run by agents. Each finding is a claim to recheck before
  editing, not an accepted fact.
- `AGENTS.md` ("Shared paths") governs which slices need the `contract-change`
  label, lead review and an accepted ADR. `.github/workflows/shared-paths.yml`
  enforces the label.
- Once registered, this plan is subordinate to `specs/001-financial-evidence-lab/`
  and to the workstream entry. It restates no `T####` state.

## Scope

In scope:

- Factual corrections to architecture, development, operator, package and
  handoff docs.
- The doc index, the glossary and the credential registry (names only).
- Archiving historical handoff and research files.
- Status-line and back-link corrections to ADRs and specs, through a dedicated
  ADR (slice S4).

Out of scope:

- The hosted extraction worker topology. `infra/railway/worker.json` starts no
  `extraction` consumer. Docs will state this gap; the infra fix goes to a
  separate issue (D6).
- Code comments that repeat a stale recipe (`evals/harness/corpus_qa.py:55`,
  `:1359`). These go to a follow-up.
- Re-deciding any ADR. S4 records decisions the lead makes; it does not make
  them.
- Promoting `docs.yml` to a required check.
- Moving `docs/superpowers/plans/`. ADR-0017, ADR-0024 and ADR-0025 link into
  it (see D3).

## Acceptance criteria

| ID | Observable result | Basis |
|---|---|---|
| AC-1 | No claim corrected in S1 still disagrees with the code at the PR head. The PR body gives one claim → evidence path row per corrected finding. | Audit findings rechecked against code |
| AC-2 | `docs/development/testing.md` no longer says it matches CI "exactly". It lists every remaining difference between `make ci` and `.github/workflows/ci.yml`. | `Makefile`, `ci.yml` |
| AC-3 | Install instructions in `README.md`, `local.md` and `testing.md` match how CI installs dependencies (hash-pinned lock). | `ci.yml:120` |
| AC-4 | The env-var table in `local.md` lists every `FEL_*` variable the code reads, or links to a single source that does. `FEL_DEPLOYMENT_MODE` and its `public` default are stated. | `grep` over `apps/`, `workers/`, `packages/` |
| AC-5 | `CREDENTIALS.md` names every credential variable the code reads. It contains no values. | Same `grep`, restricted to credential-type variables |
| AC-6 | Apart from listed exclusions, every tracked Markdown file is reachable from `docs/README.md` directly or through a sub-index it links. | Index script (Verification) |
| AC-7 | `STATUS.md` opens with a current-state section dated on or after the S3 merge. Its history moves to an archive file. Every "Needs the integration lead" item from `remaining-work-2026-10-27.md` appears in it or is marked closed with a PR. | Lead review against the snapshot |
| AC-8 | No `workstreams.yaml` entry whose PR has merged reads `ready` or `active`. | `git log` against yaml statuses |
| AC-9 | Archived files live under `docs/archive/`. Every inbound link resolves. No personal email address remains in any archived brief. | `lychee` offline; `grep` for `@` addresses |
| AC-10 | The ADR index and ADR status lines record the lead's D4 decisions. ADR-0005 links back to ADR-0021. Spec 002–005 status lines state their current state. A `specs/README.md` index exists. | S4 ADR; lead review |
| AC-11 | `handoff/README.md` is the single resume entry. `CLAUDE.md` and `FABLE_ORCHESTRATION.md` link to it instead of repeating a reading order. | Read-through by a fresh reviewer |
| AC-12 | Every changed page that carries a "Source references verified against commit" stamp shows a SHA at or after the edit. | `grep` over changed files |

Each slice must keep the Docs workflow (links and markdownlint) and the Shared
paths check green.

## Decisions

| ID | Decision | Options | Recommendation | Owner |
|---|---|---|---|---|
| D1 | Requirements owner | (a) One GitHub issue plus a workstream entry with `allowed_paths`, per `CLAUDE.md`. (b) Proceed unregistered. | (a). (b) breaks the resume sequence and the allowed-paths rule. | Integration lead |
| D2 | Who carries the shared-path slices (S3, S4)? | (a) The lead (CODEOWNERS shows `@wilsonhj` on `docs/decisions/` and `docs/handoff/`) authors or authorizes them. (b) An agent drafts them under a `contract-change` issue. | (b): the agent drafts, the lead reviews and labels. | Integration lead |
| D3 | How much to archive | (a) Partial: S2 moves only files that no shared path links to; S3 moves files the ledger links to; `superpowers/plans/` and `production-auth.md` stay in place because ADRs link to them. (b) Full move, with ADR link edits in S4. | (a). Avoids ADR edits made only to fix links. | Integration lead |
| D4 | ADR content | ADR-0014: accept, or record why it stays Proposed. ADR-0012: amend or withdraw (an OpenAI adapter now exists, and its revisit triggers have fired). ADR-0002: add a related-ADR line. | Accept ADR-0014. Amend ADR-0012 to point at ADR-0026. | Integration lead |
| D5 | `make typecheck` omits `scripts/db`, which CI checks | (a) Add `scripts/db` to the `Makefile` in S3. (b) Document the gap only. | (a). A one-path change removes a documented trap. | Integration lead |
| D6 | No hosted worker runs the `extraction` queue | (a) Docs state the gap and link a new infra issue. (b) Docs only. | (a) | Integration lead |
| D7 | `evals/datasets/benchmark-seed/README.md` says the seed is not T0214a evidence, but the ledger checks T0214a | Correct the README, or annotate the ledger | Lead decides; S4 records the result | Integration lead |

## Slices

The slices depend on each other as follows:

- S0 must come first.
- S1 and S2 then run in parallel.
- S3 depends on S2's archive directory.
- S4 can run alongside S3.
- S2 archives `remaining-work-2026-10-27.md` only after S3 has moved its open
  items into `STATUS.md`.

### S0: Registration (lead)

- Changes: one GitHub issue, and a workstream entry `DOCS-DRIFT-REMEDIATION`
  in `workstreams.yaml` covering branches and `allowed_paths` for S1–S4.
- Prerequisites: D1 and D2.
- Done when: the issue exists and the entry is merged.

### S1: Correctness fixes in non-shared docs (plain docs PR)

Every finding is rechecked against code before it is edited. A finding that
fails the recheck is dropped and listed in the PR body.

- **Architecture: `docs/architecture/overview.md`, `system-design.md`,
  `visualization-roadmap.md`.**
  - Remove or mark as planned the nonexistent `tools.py` role allowlist
    (`system-design.md:336`).
  - State the worker queue topology and the D6 gap. `worker.json` defaults to
    the `ingestion` queue; the API enqueues on `extraction`.
  - Limit the budget and usage claims to retrieval (`costs.*` is called only
    from `apps/api/app/retrieval.py`).
  - Mark the Desk as fixture-only.
  - Redraw the layer diagram to show that the API imports `fel_workers.extraction`
    (15 imports), and add `fel_ontology`.
  - Document the two approved contract copies: the worker's vendored schema and
    `CLAIM_JSON_SCHEMA`.
  - Document what currently has no runtime caller or no description: the
    "Scheduler", the index build path, the API's direct storage reader, the
    per-replica rate limiter, the web extraction proxy routes, and which
    service applies migrations at deploy.
  - Fix the stale paths (`persist_types.py`, `_assert_run_open`, 12 FSM stages)
    and align the verified-commit stamps.
- **Operator and infra: `workers/src/fel_workers/extraction/OPERATOR.md`,
  `workers/README.md`, `infra/railway/README.md`.** Rewrite the terminal-run
  job paragraph to match `consumer.py::_park_terminal_run_job`. Add the queue
  topology.
- **Web: `apps/web/README.md`.** Rewrite it as the app-level README. Cover all
  routes, both evidence sources, the server proxy, and the
  `FEL_DEPLOYMENT_MODE` / `FEL_WORKSPACE_ID` / `FEL_AUTH_MODE` variables
  (ADR-0027).
- **Packages: `packages/retrieval/README.md`, `packages/ontology/README.md`,
  `packages/calculation-engine/README.md`.**
  - Retrieval: complete the module map.
  - Ontology: replace the PYTHONPATH claim.
  - Calculation engine: fix the title and the #197 citation.
  - `packages/contracts/README.md` is a shared path, so it goes to S4.
- **Development: `docs/development/local.md`, `testing.md`,
  `quality-gates.md`, root `README.md`.**
  - AC-2, AC-3, AC-4.
  - Require pgvector ≥ 0.8.2.
  - Add the `FEL_FIXTURE_INGEST` worker mode.
  - Recommend `make install-py`.
  - Use one migration method (`scripts/db/migrate.py`) everywhere.
  - Fix the CI job list (7 required checks plus `docs.yml` and
    `extraction-acceptance.yml`), the `show-report` advice, the stray Testing
    Library entry, and the build env vars.
  - Remove "(T0002)" from the `local.md` title.
  - Wording depends on D5. If S3 fixes the `Makefile` first, drop the
    `scripts/db` note.
- **Evals: `evals/reports/corpus-qa/SCHEMA.md`.** Replace the
  migrations-0001+0002 `psql` recipe with `scripts/db/migrate.py`.
- **Handoff, non-shared files: `docs/handoff/CREDENTIALS.md`,
  `docs/handoff/README.md`, `docs/handoff/FABLE_ORCHESTRATION.md`.**
  - AC-5.
  - Replace "Current briefs" and "Current state" with live pointers.
  - Use one source-of-truth order.
  - AC-11.
- **Glossary: `docs/glossary.md`.**
  - Add: retrieval receipt, source clock, vintage / missing observation,
    checkpoint / stage output, extraction run, conflict occurrence, approved
    extraction / record version, workspace, corpus version / pin, index
    version / lane, retrieval trace, Evidence Reader, Earnings Update Desk,
    golden file and gates, calibration / `isotonic-v1`, worker role, API
    budget, migration ledger.
  - Correct the "Deployment mode" and "ADR" entries.
- **Index: `docs/README.md`, `docs/research/README.md`.** Add
  `remaining-work-2026-10-27.md` (until S2 archives it),
  `research/financial-evidence-skills-review.md`,
  `evals/datasets/calibration/README.md` and
  `workers/src/fel_workers/extraction/ISOTONIC.md`.

`CLAUDE.md` is not on the shared list. It changes here only to link
`handoff/README.md` (AC-11).

- Expected result: AC-1 through AC-6, AC-11 and AC-12. Zero shared paths
  changed.

### S2: Archive non-shared-referenced history (plain docs PR)

- **Moves into `docs/archive/`:**
  - `handoff/2026-07-ext/`: `EXTERNAL_AGENT_BRIEF.md`,
    `SESSION_BRIEF_SEC_EGRESS.md` and `EXT_EXECUTOR_BRIEF_V2.md`, with the
    personal email address redacted.
  - `research/`: `RECONCILIATION-2026-07-16.md`,
    `2026-09-09-open-issue-audit.md` and both `finrobot-cherry-pick-*.md`.
  - `handoff/2026-10/`: `remaining-work-2026-10-27.md`, after S3 merges.
- **New file:** `docs/archive/README.md`, which says archived files are
  historical and never authoritative.
- **Updated:** the inbound links in non-shared files, and the index.
- **Prerequisite:** recheck that no shared path links to any moved file. At
  `f4b1197`, none did.
- **Expected result:** AC-9 for these files. Zero shared paths changed.

### S3: Ledger refresh (`contract-change`, lead review, no ADR)

- **`STATUS.md`:**
  - Add one current-state section covering merged work since 2026-09-16,
    open lead decisions, blockers, and the dependency graph from the
    remaining-work snapshot.
  - Move the history (current lines ~148–425) to
    `docs/archive/handoff/STATUS-history-2026-09.md`.
- **`workstreams.yaml`:**
  - Set `OFFLINE-CALIBRATION-DATASET`, `OFFLINE-ISOTONIC-CALIBRATOR` and
    `DOCS-EXECUTIVE-ARCHITECTURE` to `merged`, with PR@SHA.
  - Re-scope or close `BACKLOG-EXECUTION-CONTROL`.
  - Record #339–#359 where they map to packages.
- **Moves into `docs/archive/handoff/2026-09/`:** `execution-2026-09-09.md`,
  `external-agents-2026-09-16.md` and `implementation-agents-2026-09-16.md`.
  Move `research/2026-09-09-backlog-resolution-spec.md` and
  `research/2026-09-16-completion-spec.md` to `docs/archive/research/`.
  Update the ledger's links to them in the same PR.
- **`AGENTS.md:62`:** the label check exists in `shared-paths.yml`; replace
  the "still unbuilt (#141)" sentence.
- **`Makefile`:** add `scripts/db` to `typecheck`, if D5 is (a).
- **Expected result:** AC-7, AC-8, and AC-9 for the moved files.

### S4: Reconcile ADR and spec status (`contract-change`, accepted ADR, lead review)

- **New ADR-0032.** It authorizes status-line, back-link and
  maintenance-note edits to ADRs and specs, records the D4 and D7 outcomes,
  and changes no decision content. Its precedent is ADR-0013, the
  ledger-reconciliation ADR.
- **ADRs:**
  - ADR-0014 status, per D4.
  - ADR-0012 amendment or withdrawal, per D4.
  - ADR-0002 related-ADR line.
  - ADR-0005 "superseded in part by ADR-0021" line.
  - ADR-0001 `Date:` line.
  - Matching rows in `docs/decisions/README.md`.
- **Specs:**
  - Status lines for specs 002–005.
  - A "checkboxes not maintained; canonical ledger governs" note on
    `specs/002/tasks.md` and `specs/003/tasks.md`.
  - Quickstart fixes: the retrieval-runs events route, `make
    eval-retrieval-gate`, real test paths, no `uv` workspace.
  - Remove the restated stack from `specs/001/plan.md:10`.
  - Add a new `specs/README.md` lifecycle table.
- **Other shared docs:** `packages/contracts/README.md:30` (the parity test
  exists) and `db/migrations/README.md:27` (the directory is no longer empty).
- **Expected result:** AC-10.

## Verification

All commands are read from `.github/workflows/docs.yml` and
`shared-paths.yml`. Results below are from planning only; nothing has been
implemented.

| Check | Command or route | Covers | State |
|---|---|---|---|
| markdownlint on changed files | `npx --yes markdownlint-cli2@0.18.1 <changed .md>` (`docs.yml` lint job) | All slices | Available locally. Passed on a sample file during planning. |
| Offline links and anchors | `lychee --offline --include-fragments --hidden './**/*.md'` (`docs.yml` links job) | AC-9, all slices | `lychee` is not installed locally. Planned route: the `lycheeverse/lychee` container (Docker is present, image pull unverified), or the CI job. A local Python check found 0 broken relative links at `f4b1197` but does not check anchors. |
| Shared-path diff | `bash .github/scripts/list-changed-paths.sh <merge-base> HEAD` | S1/S2 touch zero shared paths; S3/S4 carry the label | Available locally. Not yet run against a candidate. |
| Index reachability | Script that compares `git ls-files '*.md'` with links reachable from `docs/README.md`, following sub-indexes | AC-6 | Planning version exists in the session scratchpad. It needs sub-index traversal before it counts as evidence. |
| Claim recheck | Per-finding `grep` or path check against the PR head, tabulated in the PR body | AC-1, AC-4, AC-5, AC-12 | Planned. During planning, 8 findings were rechecked by hand and all held: `tools.py` absent, worker default queue, `Makefile` vs `ci.yml` mypy paths, the `AGENTS.md` label sentence, ADR-0014 status, the quickstart route, and two workstream statuses. |
| Ledger consistency | `git log --oneline` against `workstreams.yaml` statuses and `STATUS.md` items | AC-7, AC-8 | Planned (lead review). |
| Independent review | One fresh reviewer per PR, given the findings list and the diff, not the author's verdict | All slices | Planned. S4 also needs lead review of the ADR text. |

No application tests apply: S1–S4 change no executable code. The exception is
the D5 `Makefile` line, which must be checked by running `make typecheck` and
seeing mypy cover `scripts/db`.

## Risks

| Risk | Assumption that makes the slice safe | Check that could disprove it |
|---|---|---|
| Docs end up describing a bug as the design (the extraction queue gap) | Gaps are written as "known gap, see issue", never as the design | Reviewer reads every new "is" statement against D6 |
| An archive move forces an unplanned shared-path edit | S2 moves only files with zero shared-path referrers | Rerun the referrer `grep` and the shared-path diff before opening the PR |
| An audit finding is wrong and gets "fixed" into an error | Every finding is rechecked against code before it is edited | Claim → evidence table in each PR body |
| The `STATUS.md` rewrite drops an open item | Every remaining-work lead item maps to a `STATUS.md` line or a closing PR | Lead checks the S3 PR against the snapshot |
| Drift comes back | Verified-commit stamps are updated whenever a page is touched | Optional follow-up: add an index-completeness step to `docs.yml` (a shared path) |

## Blockers and next action

- **Readiness: pending decision.** S0 needs D1 and D2 before any slice can be
  dispatched under `CLAUDE.md`. S3 needs D5. S4 needs D4 and D7.
- **Not blocked by any decision:** recheck the remaining audit findings
  read-only, and extend the index script to follow sub-indexes.
- **Next action:** the integration lead decides D1–D3 and registers S0. S1 and
  S2 can then start in parallel.
