# Remaining work

Instructions for the next implementation agent and for the integration lead.
This file is a snapshot, not a task ledger. Checkbox state lives only in
[`specs/001-financial-evidence-lab/tasks.md`](../../specs/001-financial-evidence-lab/tasks.md).
Package status lives only in [`workstreams.yaml`](workstreams.yaml). If either
file disagrees with this page, those files win, then GitHub.

**Snapshot.** `origin/main` at `59bbf7e` (`docs: make the docs findable and correct stale facts`, #349), fetched Monday, October 26, 2026, 10:38 PM Pacific. Six pull requests were open. None had a GitHub review.

**Trunk is green.** On `59bbf7e`, required CI, the extraction cross-stack acceptance job, and the weekly dependency-advisory scan completed successfully. `node scripts/audit-bulk.mjs` reported no blocking vulnerabilities. Do not reopen #347-style lockfile work unless a new advisory appears.

## Who does what

| Kind of work | Who |
| --- | --- |
| The edits in [Do now](#do-now) | Any implementation agent. No new design, no credential, no canonical-checkbox edit. |
| Sequencing, acceptance, dispatch keys, ADR acceptance, hosted credentials, task checkboxes | Integration lead. Use Claude Opus 5.5 extra high for that planning pass. |
| Milestone product work in [After the lead freezes the next slice](#after-the-lead-freezes-the-next-slice) | An implementation agent, only after the lead names the issue, branch, and allowed paths. |

Agents do not mark `T####` tasks complete, do not flip `workstreams.yaml` status, and do not write "Accepted by the integration lead" into an ADR.

## Do now

These are bounded edits. Each one has a current head, the files to touch, and a finish line. Do them on the existing pull-request branches. Do not start a new design branch for them.

### 1. Land the two approved pull requests

Reviewed and approved against these heads. No production-behavior change beyond what the diff already contains.

| PR | Head | Finish line |
| --- | --- | --- |
| [#351](https://github.com/wilsonhj/financial-evidence-lab/pull/351) isotonic nesting bound | `0060893` | Lead approves and squash-merges. 16 containers allowed, 17 returns `limit_exceeded`, enforced on `predict` and `evaluate` through `_validate_artifact`. |
| [#352](https://github.com/wilsonhj/financial-evidence-lab/pull/352) calibration boundary tests | `f6d5b34` | Lead approves and squash-merges. Tests only. |

Optional follow-up, not a merge blocker for #352: add one calibration cell with exactly 20 negatives (100 rows, 80 positive). A calibration-only raise of the negative floor from 20 to 21 would still pass the tests that exist today.

### 2. [#353](https://github.com/wilsonhj/financial-evidence-lab/pull/353) — keep the merge-base, stop hiding paths

Head `90da4f9`. File: `.github/workflows/shared-paths.yml`.

The merge-base comparison is the right fix. A two-dot diff against the base tip blamed #352 for files that landed on `main` in #348 and #349. Keep `git merge-base`.

Replace the name-only diff so a rename or a non-ASCII path cannot skip the matcher:

```bash
changed=$(git diff --no-renames --name-only -z "$merge_base" "$HEAD_SHA" | tr '\0' '\n')
```

`--no-renames` keeps the source path of a move (a rename of `packages/contracts/api.ts` or `AGENTS.md` must still fail the check). `-z` stops Git from C-quoting a path such as `docs/decisions/café.md`, which the current `grep` does not match. A path that itself contains a newline can still split a record; that case is out of scope.

Prove it with three local diffs before pushing:

- A branch off `167ab22` that edits only `AGENTS.md` must exit 1.
- `git mv packages/contracts/api.ts` to a non-shared path must exit 1 and the output must still contain `packages/contracts/api.ts`.
- #352's head against base `59bbf7e` must exit 0, because its only file is `evals/tests/test_calibration_dataset.py`.

This file is under `.github/`. The pull request already has the `contract-change` label. Do not add an ADR.

### 3. [#354](https://github.com/wilsonhj/financial-evidence-lab/pull/354) — the code can stay; the acceptance claim cannot

Head `ee8f961`. Label `contract-change` is present. There is no GitHub review.

Set the `Status:` line of these three files back to **Proposed**:

- `docs/decisions/ADR-0029-retrieval-receipts.md`
- `docs/decisions/ADR-0030-explicit-fred-missing-values.md`
- `docs/decisions/ADR-0031-named-source-clocks.md`

They currently say `Accepted by the integration lead on PR #354 (2026-10-27)`. That sentence is false. Update the index rows in `docs/decisions/README.md` and the pointers in `docs/research/financial-evidence-skills-review.md` to Proposed as well. Point the leftover "rows are dropped" and "clocks are an open candidate" sentences in ADR-0029 and ADR-0030 at ADR-0030 and ADR-0031.

Leave the worker implementation. Receipts, explicit `"."` gaps, and named source clocks are the right shape. They sit on the existing host allowlist, size cap, and deadline.

Two code fixes still open on this head:

- `workers/src/fel_workers/ingestion/fred.py` still does `date.fromisoformat(str(item["date"]))` and `str(item["value"])`. Accept only a `YYYY-MM-DD` string and an exact string value. A JSON number must raise `FredIngestionError` and must not become a float before `Decimal`.
- The temporal suite must not record a future `"."` gap as known at an earlier cutoff. Give that row a `published_on` inside the archive and expect it only after that day.

After those edits, stop. The integration lead accepts or rejects the three ADRs in a review on this pull request. Do not write the acceptance into the files yourself.

### 4. [#350](https://github.com/wilsonhj/financial-evidence-lab/pull/350) — stop presenting fixture copy as evidence

Head `5aad3d6`. Marked ready for review. The follow-up commit only reframes the camera. These strings are still in the tree:

- `apps/web/src/components/EvidenceGraph3D.tsx` — `sha256=9f4b8a0e`, `sha256=c25e27b4`, `sha256=75fad38c`, and `Staged with verified lineage`. Those hashes are truncated git SHAs, not span hashes. Remove them. Label the view as a fixture schematic, or bind every hash to a real evidence or calculation record. Do not say "verified" unless the same admissibility rule that paints the node says so.
- `apps/web/src/app/desk/DeskClient.tsx` — `+$60.4m` for both 108% and 109% NRR, under the heading `Deterministic Decimal Bridge`. `782 * 0.08` is not `60.4`. Delete the bridge claim. Do not invent a `$790–794m` corridor in copy that the figure does not draw.
- `apps/web/src/components/ObservatoryFlowViz.tsx` — the rejected box always says `Future / cross-version`. Summarize the codes `partitionCandidates` already returns. `MOCK_TRACE` also rejects `dedupe_near_duplicate`.
- `docs/architecture/visualization-roadmap.md` — say the desk chart and 3D graph are illustrative fixture schematics until they are derived from Decimal strings or verified traces.

Add one test that fails if the inspector contains `sha256=` or `verified lineage`, and one that fails if the NRR step stays `+$60.4m` after the call is selected.

### 5. [#355](https://github.com/wilsonhj/financial-evidence-lab/pull/355) — correct the amendment, leave it Proposed

Head `287be97`. One file: `docs/decisions/ADR-0010-cross-repo-pattern-adoption.md`. Status is already Proposed. Keep it Proposed. The `contract-change` label is present.

Fix these claims:

- The amendment says the Context's replay-only retrieval sentence is unchanged. The Context has no retrieval-run sentence. Its SSE sentence says the same-origin proxy is deferred to #135. #135 is closed, and the proxy is `apps/web/src/lib/extraction/transport.ts` forwarding to `/v1/extraction-runs/{id}/events`. Write that #135 shipped the proxy and consumer without `Last-Event-ID` epoch, reset, or descriptor/body split, so decision 5 was not met by the implementation that closed #135.
- "About seventy commits" from `a25bf7c` to `59bbf7e` is wrong. The first-parent count is 125. Use 125, or delete the count and keep the SHAs.
- Retarget stale anchors the amendment still calls current: `workflow.py` is 463 lines, so `workflow.py:477-489` is past EOF; the resume key is the partial unique index in `db/migrations/0004_extraction_core.sql`; Principle II is `.specify/memory/constitution.md` around lines 40–41, not the sync-impact comment at lines 18–19.

The recall figure `0.4692` against `0.9000` matches `evals/reports/retrieval-gate/2026-09-01-synthetic-seed.json`. Leave that correction in place.

## Needs the integration lead

Use Claude Opus 5.5 extra high. This pass decides order, acceptance, and credentials. It does not implement the product slices below.

Do these in this order:

1. **Review the six open pull requests.** Approve #351 and #352. Request the edits in [Do now](#do-now) on #353, #354, #350, and #355. Squash-merge #351 and #352 when checks are green. Do not treat ADR-0029, ADR-0030, or ADR-0031 as accepted until you write an authorization record on #354 and the Status lines are updated in a later commit that quotes that record.
2. **Reconcile the handoff ledger.** `docs/handoff/workstreams.yaml` still has `DOCS-EXECUTIVE-ARCHITECTURE` as `active` after #342 merged (`167ab22`), and `OFFLINE-CALIBRATION-DATASET` / `OFFLINE-ISOTONIC-CALIBRATOR` as `ready` after #340 (`bc0435b`) and #339 (`b9c3189`) merged. `docs/handoff/STATUS.md` still starts at September 16. Update both only as a `contract-change` ledger edit. Do not change a dispatch key, dependency, or credential policy in that same edit unless you intend a new dispatch.
3. **Close or re-scope issues whose code is already on `main`.** #337 (offline isotonic) is implemented on `main` by #339; #351 is the residual test and depth bound. #344 is not in the open set. #96 and #87 stay open only as trackers for #108. #61's review API and web slices are merged; the issue stays open because the 25-user load gate is not met.
4. **Freeze the next product contract before any agent implements it.** The next decision is public sessions and user-funded inference (#324, ADR-0026 is accepted as a direction, the session/bootstrap/custody interfaces are still Proposed in `docs/research/public-auth-byok-contract.md`). Until that freeze exists, public web business routes correctly return HTTP 503 (`apps/web/src/lib/deployment-mode.ts`, ADR-0027). Do not weaken that guard to demo a signed-in user.
5. **Decide provider direction (#195).** ADR-0012 is Proposed. Explicit-key OpenAI generation (#328) and embeddings (#329) are merged libraries and are not called from `apps/api` or `workers`. Accept or reject ADR-0012 before anyone wires a live provider. There is no owner-key fallback.
6. **Name the hosted targets before anyone claims #61 or #108 done.** #61 bulk-review p95 on the shared local Docker VM was 4,147 ms, 1,002 ms, then 1,501 ms against a 1,000 ms limit (`apps/api/EXTRACTION_LOAD.md`). #108 has local preparation and no hosted run. Provision the database target and the Railway web/API/worker plus shared storage target, or say explicitly that those issues stay blocked. Credential names only, never values (`docs/handoff/CREDENTIALS.md`).

## After the lead freezes the next slice

Do not start these in parallel with each other. `packages/contracts/**` and `db/migrations/**` have one owner at a time. Cap active packages at four. Each slice needs an issue, a branch from `workstreams.yaml`, and allowed paths.

Dependency order:

```text
#324 public session + BYOK custody
        |
        +--> #292 hosted identity acceptance
        +--> #195 provider decision --> wire OpenAI adapters
                |
                +--> #177 live cutover (credentials, embeddings choice, Alpha Vantage budget)
                        |
                        +--> #56 / T0112 live 20-issuer corpus
                        +--> #132 / T0215 live 65-question retrieval gate
                        +--> #191 live usage accounting

#61 load gate on a dedicated database (independent of #324, blocked on a host)
#108 hosted reader smoke (independent of #324, blocked on Railway + shared storage)

#61 load accepted --> #62 wire isotonic-v1 + human labels (T0306, T0307, T0310)
        |
        +--> #64 approved facts to model nodes, sparse scenarios (T0404, T0405)
                |
                +--> #65 model UI (T0406–T0408)
                +--> #66 forecast contract and baselines (T0501–T0503, T0507)
                        |
                        +--> #67 backtests and intervals (T0504, T0505, T0508)
                                |
                                +--> #68 audit, export, 300-question gate, release artifact
                                     (T0509–T0513, T0214b)
```

What is already on `main` and must not be rebuilt:

- M0 platform, contracts, CI, and migrations `0001` through `0011`.
- M1 ingestion, including the HTTP host allowlist, decoded size cap, and per-attempt deadline from #345 (`470ef51`).
- M2 retrieval, claims, and Search Observatory. Mock Recall@10 is 0.4692 against a 0.90 live gate. That gap is #177 / #201, not a broken mock.
- M3 extraction runtime, review API, and approved-record history. Every proposal still requires human review.
- Offline calibration validator (#340) and weighted PAV `isotonic-v1` (#339, depth bound in #351). Neither is wired into proposal scoring. `workers/src/fel_workers/extraction/isotonic.py` must stay unimported by the dataset package, and the reverse.
- `packages/calculation-engine` (formula AST, cyclic groups, Decimal). Nothing in `apps/api`, `apps/web`, or `workers` imports it. The M4 UI and forecast packages are unbuilt. `workers` forecasting is an empty placeholder.

Canonical tasks still unchecked, for the lead's planning pass only: `T0112`, `T0215`, `T0306`, `T0307`, `T0308`, `T0309`, `T0310`, `T0401`–`T0410`, `T0501`–`T0505`, `T0507`–`T0513`, `T0214b`. Several of `T0308`, `T0309`, and `T0401`–`T0403` have merged code and are open because acceptance evidence is missing. Read the sentence on each line in `tasks.md` before treating the box as "not started." `T0211`–`T0213` and `T0506` are deferred post-MVP.

## Known blockers

| Blocker | What it stops | What unblocks it |
| --- | --- | --- |
| No per-user web session | Public business routes return 503 | Lead freezes #324, then an agent implements it |
| ADR-0012 Proposed | Wiring a live model provider | Lead accepts or rejects #195 |
| No user-owned credential store | Billable provider calls | #324 custody, then #191 accounting |
| #61 load gate unmet | Checking T0308/T0309, starting #62 | Dedicated database target, same workload, no threshold change |
| #108 hosted smoke not run | Closing the production reader path | Railway target, shared storage, lead-provisioned credentials |
| Live corpus and retrieval gates | T0112, T0215, release section 19.6 | #177 after credentials and the embeddings choice |
| Human labels for calibration | T0306/T0310 | #62 after #61 and a real adjudication set. Synthetic fixtures are not that set |
| Calculation engine not integrated | M4/M5 product | #64 after #62. Do not import the engine from a UI mock and call it done |
| `workstreams.yaml` status drift | Safe dispatch | Lead ledger edit. Agents do not flip status |

## Do not

- Do not edit `specs/001-financial-evidence-lab/tasks.md` checkboxes in an implementation pull request.
- Do not deploy API and worker with different local storage directories. Citations will resolve and the bytes will not.
- Do not lower Recall@10, the 1,000 ms review budget, or the 0.85/0.80 review thresholds to make a gate pass.
- Do not use a shared server bearer in the public Next.js app as a stand-in for a user.
- Do not put credential values in issues, commits, logs, fixtures, or this file.
