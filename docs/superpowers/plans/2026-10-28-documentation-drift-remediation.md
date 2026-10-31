# Documentation drift remediation

Status: Decisions D1–D8 accepted by the integration lead on 2026-10-29 and
recorded in #363, the requirements owner for this package. The workstream entry
is added in S3. S1 and S2 are ready to dispatch; S3 and S4 follow the slice
order below.

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

Researched on 2026-10-29 against `main` @ `f4b1197` and GitHub. The
integration lead accepted every recommendation below on 2026-10-29; #363 holds
the record. The D6 follow-up is #362. The D8 authorization was posted on #354.

| ID | Recommendation | Lead action |
|---|---|---|
| D1 | One tracking issue. Register the workstream in S3, not before. | Open the issue |
| D2 | Agent drafts every slice. Lead labels, reviews and merges. | Confirm |
| D3 | Partial archive as planned. Leave `superpowers/plans/` and `production-auth.md` in place. | Confirm |
| D4 | Accept ADR-0014. Amend ADR-0012 to record that a revisit trigger fired, keep it Proposed, and cross-link ADR-0026. | Decide both |
| D5 | Add `scripts/db` to `make typecheck`, authorized by ADR-0032 in S4. | Confirm |
| D6 | Docs only: hosted extraction is withheld on purpose. Open a follow-up infra issue blocked by #62. | Confirm; open the issue |
| D7 | No ledger change. Reword the benchmark-seed README in S1. | Confirm |
| D8 | Post the missing #354 authorization (new item) | Authorize, or revert the status lines |

### D1: Requirements owner

- **Evidence.** `CLAUDE.md` asks for an assigned issue and a workstream
  entry. Registering a workstream edits `workstreams.yaml`, which is itself a
  shared path. Recent precedent is lighter: #357 (the remaining-work
  snapshot) merged with "Package ID: none (dispatch snapshot, not a
  workstream)". #342 and #348 were docs PRs carrying `contract-change`.
- **Recommendation.** Open one GitHub issue that lists S1–S4 with their
  allowed paths. Register `DOCS-DRIFT-REMEDIATION` in `workstreams.yaml` as
  part of S3, which edits that file anyway, instead of in a separate
  ledger-only PR first.
- **Why.** It satisfies the resume sequence (an issue exists) without a
  shared-path PR whose only content is the registration.

### D2: Who carries S3 and S4

- **Evidence.** CODEOWNERS assigns `docs/decisions/` and `docs/handoff/` to
  `@wilsonhj`. All recent `contract-change` PRs (#338–#359) were opened under
  that account and merged by it. #357's handoff names the lead as the one who
  "decides … then dispatches".
- **Recommendation.** An agent drafts all four slices as draft PRs. The lead
  applies `contract-change`, posts the authorization record, reviews and
  merges S3 and S4. This matches current practice.

### D3: Archive scope

- **Evidence.** These files link to the September cards, `production-auth.md`
  or `superpowers/plans/`:
  - ADR-0017, ADR-0024 and ADR-0025
  - `STATUS.md` and `workstreams.yaml`

  No shared path links to the July EXT briefs, the 10-27 snapshot,
  `RECONCILIATION-2026-07-16.md`, the open-issue audit or the FinRobot
  studies.
- **Recommendation.** Keep the partial archive as planned:
  - S2 moves the files with no shared-path referrers.
  - S3 moves the ledger-linked files and fixes their links.
  - `superpowers/plans/` and `production-auth.md` stay where they are.
- **Why.** Moving the files ADRs link to would mean ADR edits made only to fix
  links. Add a `superpowers/plans/README.md` saying the September plans are
  historical, so readers aren't misled.

### D4: ADR-0014 and ADR-0012

- **ADR-0014 evidence.** The Proposed design is fully live:
  - `scripts/db/migrate.py`
  - `make db-migrate` / `db-check`
  - CI migration steps (`ci.yml:185–198`)
  - Railway `preDeployCommand` in both services

  It merged via #247 at `75fad38` (`STATUS.md:307`). Its revisit triggers (a
  no-transaction migration; more than one schema writer) have not fired; the
  worker only runs `--check`. CLAUDE.md requires an accepted ADR for
  migration changes, so leaving it Proposed leaves every future migration PR
  formally unauthorized.
- **ADR-0014 recommendation.** Accept it, effective at #247, recorded in
  ADR-0032.
- **ADR-0012 evidence, trigger that has fired.** The "any live provider is
  wired" trigger (`ADR-0012:541`) has fired:
  `git grep 'openai' -- packages/providers` matches
  `openai_structured.py` and `openai_embeddings.py`.
- **ADR-0012 evidence, trigger that has not.** The "Recall@10 below 90%"
  trigger has not effectively fired. The 0.4692 in
  `evals/reports/retrieval-gate/2026-09-01-synthetic-seed.json` was measured
  with `provider: mock` and `embedding_model: mock-embed-retrieval-gate-v1`,
  so it says nothing about real retrieval quality. The earlier audit
  overstated this point.
- **ADR-0012 evidence, other.** The Arm A / Arm B benchmark that the
  mandatory trigger requires has not run; nothing outside the ADR mentions
  it. ADR-0026 has since authorized OpenRouter and later direct
  OpenAI/Anthropic keys for user-funded inference, while keeping "OpenAI
  remains the accepted model baseline".
- **ADR-0012 recommendation.** Do not withdraw it: the substitution question
  it governs is still open. Add an amendment that:
  - records that the live-provider trigger fired (an OpenAI adapter now
    exists, so the incumbent can be measured);
  - states that the Recall trigger has not fired on real embeddings;
  - restates that the Arm A/B benchmark is still the ratify-or-withdraw
    event;
  - cross-links ADR-0026 for the BYOK scope.

  Add "Related: ADR-0012 (Proposed), ADR-0026" to ADR-0002. This is a
  premise refresh like ADR-0010 Amendment 1 (#355), not a new decision.

### D5: `make typecheck` and `scripts/db`

- **Evidence.**
  - `Makefile:59–60` omits `scripts/db`; `ci.yml:129` includes it.
  - CI's Python job, mypy included, is green on #359, so adding the path
    cannot fail on current `main`.
  - `AGENTS.md` lists `Makefile` as shared but places it in no class row.
  - ADR-0003 says standalone root-config edits need `contract-change` and an
    ADR.
- **Recommendation.**
  - Make the one-line fix.
  - Move it from S3 to S4, so ADR-0032 authorizes it alongside the other
    editorial corrections. That avoids writing an ADR for one line.
  - In S1, `testing.md` describes `make ci` without the `scripts/db` caveat
    if S4 merges first; otherwise it carries a one-line caveat.
  - Verify by running `make typecheck` and confirming mypy lists
    `scripts/db`.

### D6: Hosted extraction worker

- **Evidence.**
  - `worker.json` starts with no `--queue`, so it consumes `ingestion`.
  - The API enqueues `extraction_run` on `extraction`.
  - `validate_extraction_model_binding` (`__main__.py:289`) refuses to start
    an `extraction` worker unless `FEL_ALLOW_MOCK_LLM` is set.
  - `build_structured_llm` (`__main__.py:226`) only ever binds the mock. Its
    docstring says the live adapter replaces it in #62.
  - #62 is open, and its allowed paths exclude `infra/`.

  So omitting a hosted extraction service is deliberate fail-closed
  behavior, not an oversight. Adding one today would either crash at start
  or fabricate financials.
- **Recommendation.** S1 documents this accurately: hosted extraction is
  intentionally not deployed until a live model is bound (#62) and an
  `extraction` worker service is added. (Corrected 2026-10-31: the API
  already refuses run creation with 503 `EXTRACTION_NOT_CONFIGURED` unless
  `FEL_ALLOW_MOCK_LLM` is set, `apps/api/app/extraction/runs.py:76-82`, so
  hosted runs are refused rather than left queued.)
  Open a small follow-up issue, blocked by #62, for a second Railway service
  (`--queue extraction`) and its acceptance smoke. Do not widen #62 into
  `infra/`.
- **Open point, resolved by the code.** The earlier question of whether a
  hosted API should reject run creation is moot: it already does (see above).

### D7: Benchmark seed vs T0214a

- **Evidence.**
  - T0214a (`tasks.md:48`) is "Build the 50–100-question smoke benchmark and
    automate the Section 19.6 gates". The build exists (65 questions) and
    the gate is automated (`evals/harness/retrieval_gate.py`; the committed
    report runs all 65).
  - ADR-0013 records the lead's reconciliation that checked T0214a on that
    basis.
  - The README's caveat concerns whether the seed is *exit-gate evidence*:
    point-in-time timestamps and reproducible source-byte checks.
  - That is the separate M2 exit criterion (`spec.md:1113`), which has not
    been met.
- **Recommendation.** Leave the ledger alone. In S1, reword
  `evals/datasets/benchmark-seed/README.md`: T0214a's build and automation
  are complete, and the seed is not yet M2 exit-gate evidence until the
  timestamp and byte-verification promotion checks pass. `evals/` is not a
  shared path.

### D8: ADR-0029/0030/0031 authorization (carried over from the 10-27 snapshot)

- **Evidence.**
  - All three status lines read "Accepted by the integration lead on PR #354
    (2026-10-27)", and the index agrees.
  - #354 has no reviews, and its only comment is from the Vercel bot.
  - `remaining-work-2026-10-27.md` raised this item. #359 did not close it.
- **Recommendation.** The lead posts a one-line authorization comment on #354
  naming the three ADRs. That makes the existing status lines true with no
  file edits. Otherwise, S4 reverts the three status lines to Proposed and
  aligns the index. Either way, S3's `STATUS.md` records the outcome.

## Slices

The slices depend on each other as follows:

- S0 must come first.
- S1 and S2 then run in parallel.
- S3 depends on S2's archive directory.
- S4 can run alongside S3.
- S2 archives `remaining-work-2026-10-27.md` only after S3 has moved its open
  items into `STATUS.md`.

### S0: Registration (lead)

- Changes: one GitHub issue listing S1–S4 with their branches and allowed
  paths (D1). The `workstreams.yaml` entry is added in S3.
- Prerequisites: D1 and D2.
- Done when: the issue exists. Done 2026-10-29: #363 tracks this package,
  and #362 is the D6 follow-up infra issue, blocked by #62.

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
  - Wording depends on D5. If S4 fixes the `Makefile` first, drop the
    `scripts/db` note.
- **Evals: `evals/reports/corpus-qa/SCHEMA.md`,
  `evals/datasets/benchmark-seed/README.md`.**
  - Replace the migrations-0001+0002 `psql` recipe with
    `scripts/db/migrate.py`.
  - Reword the seed status per D7: T0214a's build and automation are
    complete; the seed is not yet M2 exit-gate evidence.
- **Hosted extraction wording (D6), in `overview.md`, `infra/railway/README.md`
  and `OPERATOR.md`.** Hosted extraction is intentionally not deployed: no
  live model is bound until #62, and no `extraction` worker service exists.
  Link the follow-up issue.
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
- **Registration:** add the `DOCS-DRIFT-REMEDIATION` entry (D1).
- **D8:** record in `STATUS.md` whether the #354 authorization was posted.
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
- **`Makefile`:** add `scripts/db` to `typecheck` (D5), with ADR-0032 as the
  authorization.
- **D8 fallback:** if the lead does not post the #354 authorization, revert
  the ADR-0029, ADR-0030 and ADR-0031 status lines to Proposed and align the
  index.
- **D4 specifics:**
  - ADR-0014 becomes Accepted, effective at #247.
  - ADR-0012 gets an amendment recording which revisit triggers have fired
    and stays Proposed.
  - ADR-0002 gains a related-ADR line.
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
the D5 `Makefile` line in S4, which must be checked by running `make typecheck` and
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

- **Readiness: ready within authorized scope.** D1–D8 are accepted (#363).
  S0 is done. The D8 authorization is posted on #354. Readiness here is not an
  implementation grant: each slice is dispatched under #363.
- **Not blocked by any decision:** recheck the remaining audit findings
  read-only, and extend the index script to follow sub-indexes.
- **Next action:** dispatch S1 and S2 in parallel under #363. Then S3, with
  the `STATUS.md` rewrite recording the #354 authorization, and S4 with
  ADR-0032.
