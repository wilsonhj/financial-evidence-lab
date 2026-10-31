# Remaining work

Instructions for the next implementation agent and for the integration lead.
This file is a snapshot, not a task ledger. Checkbox state lives only in
[`specs/001-financial-evidence-lab/tasks.md`](../../../../specs/001-financial-evidence-lab/tasks.md).
Package status lives only in [`workstreams.yaml`](../../../handoff/workstreams.yaml). If either
file disagrees with this page, those files win, then GitHub.

**Snapshot.** `origin/main` at `d79eb42` (#350), Tuesday, October 27, 2026,
06:40 UTC. Required CI on `d79eb42` is green.

**What changed since the previous snapshot (`59bbf7e`).** The six pull requests
it listed were squash-merged in this order, each brought up to date with `main`
and green on every required check before merging. None had a GitHub review,
because every one was opened from the owner account, which GitHub does not let
approve its own pull requests.

| PR | Merged as | Subject |
| --- | --- | --- |
| [#353](https://github.com/wilsonhj/financial-evidence-lab/pull/353) | `bd96e63` | Shared-path check diffs from the merge-base |
| [#352](https://github.com/wilsonhj/financial-evidence-lab/pull/352) | `f9db6f3` | Calibration boundary tests |
| [#351](https://github.com/wilsonhj/financial-evidence-lab/pull/351) | `12c380a` | Isotonic nesting bound |
| [#354](https://github.com/wilsonhj/financial-evidence-lab/pull/354) | `195443c` | FRED and market provenance (ADR-0029/0030/0031) |
| [#355](https://github.com/wilsonhj/financial-evidence-lab/pull/355) | `da66969` | ADR-0010 Amendment 1 |
| [#350](https://github.com/wilsonhj/financial-evidence-lab/pull/350) | `d79eb42` | SVG diagrams and 3D/2D visualizations |

The defects below were found after those merges and were each re-checked
against `d79eb42`. They are now follow-up work on `main`, not edits to the
merged branches.

## Who does what

| Kind of work | Who |
| --- | --- |
| The fixes in [Do now](#do-now) | Any implementation agent. No new design, no credential, no canonical-checkbox edit. |
| Sequencing, acceptance, dispatch keys, ADR acceptance, hosted credentials, task checkboxes | Integration lead. |
| Milestone product work in [After the lead freezes the next slice](#after-the-lead-freezes-the-next-slice) | An implementation agent, only after the lead names the issue, branch, and allowed paths. |

Agents do not mark `T####` tasks complete, do not flip `workstreams.yaml`
status, and do not write an ADR's acceptance into the file without an
authorization record from the lead.

## Do now

Bounded fixes. Each names the files and a finish line. Open one pull request
per item from a fresh branch off `main`.

### 1. Shared-path check: renames and non-ASCII paths still pass unlabeled

File: `.github/workflows/shared-paths.yml`. Needs the `contract-change` label.
Do not add an ADR.

Keep the merge-base comparison from #353. The `--name-only` diff still has two
holes, both reproduced on `d79eb42` and both older than #353:

- Rename detection reports only the destination, so `git mv` of a file under
  `packages/contracts/` to a non-shared path passes.
- Git C-quotes non-ASCII paths, so `docs/decisions/café.md` reaches `grep` as
  `"docs/decisions/caf\303\251.md"` and matches nothing.

Use:

```bash
changed=$(git diff --no-renames --name-only -z "$merge_base" "$HEAD_SHA" | tr '\0' '\n')
```

Finish line, as three local runs of the step's script in a full clone.
`set -u` aborts if `HAS_LABEL` is unset, and `HAS_LABEL=true` exits 0 as soon
as a shared path is detected, so the exit codes below only show up with
`HAS_LABEL=false` plus `BASE_SHA` and `HEAD_SHA` for the fixture commits:

- Renaming a file out of `packages/contracts/` exits 1, and the output names
  the source path.
- Adding `docs/decisions/café.md` exits 1.
- A branch whose only change is under `evals/tests/` exits 0.

A path that itself contains a newline can still split a record; that case is
out of scope.

### 2. FRED parsing: coerced dates and float values

File: `workers/src/fel_workers/ingestion/fred.py` (`LiveFredClient.fetch_vintage`).

The parser does `date.fromisoformat(str(item["date"]))` and
`str(item["value"])`. On `d79eb42`:

- The JSON number `20260501` is accepted as the date 2026-05-01. Python 3.11's
  `fromisoformat` also accepts compact (`20260501`) and ISO-week date strings.
- A JSON number value passes through `float` before `Decimal`:
  `12345678901234567.1` becomes `1.2345678901234568e+16`.

ADR-0030 says malformed rows fail closed. Accept only a string matching
`YYYY-MM-DD` and a string value; anything else raises `FredIngestionError`.
Finish line: tests for a numeric date, a compact date string, and a numeric
value, each raising `FredIngestionError`.

### 3. Temporal suite: a gap known before it could exist

File: `workers/tests/test_temporal_cutoff_suite.py`.

`_alfred_handler` appends `{"date": "2026-05-01", "value": "."}` to every
vintage, and the record test asserts that gap at every cutoff in `FRED_MATRIX`,
including 2026-04-10, before the series had published anything. Give the gap a
`published_on` in `_ARCHIVE`, return it only from vintages on or after that
day, and expect it only at cutoffs after that day. Do not change the existing
value expectations.

### 4. ADR-0010 Amendment 1: three wrong statements

File: `docs/decisions/ADR-0010-cross-repo-pattern-adoption.md`. Needs the
`contract-change` label. Status stays Proposed.

- "About seventy commits" from `a25bf7c` to `59bbf7e` is wrong. The
  first-parent count is 125 (162 commits in all). Use 125, or drop the count
  and keep the SHAs.
- The amendment says the Context's replay-only description of retrieval-run
  events is unchanged. The Context has no such sentence. Its SSE sentence
  (line 48) says the same-origin proxy is deferred to #135, and #135 is closed:
  the proxy is `apps/web/src/app/api/extraction/runs/[runId]/events/route.ts`,
  which forwards through `requestExtraction` in
  `apps/web/src/lib/extraction/transport.ts` to
  `/v1/extraction-runs/{id}/events`, and the browser consumer resumes with
  `Last-Event-ID`. Say that #135 shipped without the
  instance epoch, reset signal, or descriptor/body split, so decision 5 was not
  met by the implementation that closed it.
- Two anchors the citation table missed: `workflow.py:477-489` is past the end
  of the 463-line file, and Principle II is `.specify/memory/constitution.md`
  line 40, not lines 18–19.

The recall correction (`0.4692` against `0.9000`) is right. Leave it.

### 5. Desk and Observatory visualizations present fixture copy as evidence

Files: `apps/web/src/components/EvidenceGraph3D.tsx`,
`apps/web/src/app/desk/DeskClient.tsx`,
`apps/web/src/components/ObservatoryFlowViz.tsx`,
`docs/architecture/visualization-roadmap.md`.

- The 3D inspector shows `sha256=9f4b8a0e`, `sha256=c25e27b4` and
  `sha256=75fad38c`, and the text `Staged with verified lineage`. The hashes
  are made up; they are not span hashes. Remove them, or bind each to a real
  record. Label the view a fixture schematic, and do not say "verified" unless
  the admissibility rule that paints the node says so.
- The NRR dollar amount stays `+$60.4m` for both 108% (`sec-10q-nrr`) and
  109% (`call-turn-48`). Only the parenthetical changes (`(108% 10-Q)` versus
  `(109% Call)`), under the heading `Deterministic Decimal Bridge`. `60.4` is
  the residual `842.4 − 782.0` (the FY27 base total minus Q2 ARR), not either
  retention rate: `782 × 0.08` is `62.56` and `782 × 0.09` is `70.38`.
  Replacing only that label with `62.56` or `70.38` breaks the Base, Bull, and
  Bear totals, which are built on `842.4`. Derive the step and those totals
  from the selected rate, or drop the bridge claim and label the chart a
  fixture.
- The rejected box always says `Future / cross-version`. The demo run also
  rejects `dedupe_near_duplicate`. Summarize the reason codes that
  `partitionCandidates` already returns.
- In the roadmap, say the desk chart and 3D graph are illustrative fixture
  schematics until they are derived from Decimal strings or verified traces.

Finish line: one test that fails if the inspector contains `sha256=`, and,
after facts are applied with an admissible decision, if it contains
`verified lineage` (the default sublabel is `Preview · awaiting review
gates`). And one that fails if both NRR selections show the same dollar
amount. Comparing the full labels already passes, because `(109% Call)` and
`(108% 10-Q)` differ.

## Needs the integration lead

This pass decides order, acceptance, and credentials. It does not implement the
product slices below.

1. **Decide whether ADR-0029, ADR-0030 and ADR-0031 stay Accepted.**
   Each Status line says "Accepted by the integration lead on PR #354
   (2026-10-27)". That sentence is not in the `docs/decisions/README.md` index
   (those rows say Accepted, dated 2026-10-24, the ADR `Date` field) or in
   `docs/research/financial-evidence-skills-review.md` (those say "Accepted as"
   and "implemented", and do not name #354). #354's description, written by
   the owner, says the integration lead accepted all three on 2026-10-27 and
   points at `6a5af3f`. The pull request has no reviews. AGENTS.md defines an
   authorization record as a statement on the PR, by the lead, naming what is
   authorized and why. The description is a statement; it is not that record.
   Either post a lead authorization on #354 that names the three ADRs and why,
   or have an agent set the three Status lines back to Proposed and then align
   the index and the research note with that. Do not revert those two files
   by searching them for the Status-line sentence.
2. **Reconcile the handoff ledger.** `docs/handoff/workstreams.yaml` still has
   `DOCS-EXECUTIVE-ARCHITECTURE` as `active` after #342 merged (`167ab22`), and
   `OFFLINE-CALIBRATION-DATASET` / `OFFLINE-ISOTONIC-CALIBRATOR` as `ready`
   after #340 (`bc0435b`), #339 (`b9c3189`) and #351 (`12c380a`) merged.
   `docs/handoff/STATUS.md` still starts at September 16. Update both only as a
   `contract-change` ledger edit. Do not change a dispatch key, dependency, or
   credential policy in that same edit unless you intend a new dispatch.
3. **Close or re-scope issues whose code is already on `main`.** #337 (offline
   isotonic) is implemented by #339, with the depth bound and test gaps closed
   by #351. #96 and #87 stay open only as trackers for #108. #61's review API
   and web slices are merged; the issue stays open because the 25-user load
   gate is not met.
4. **Freeze the next product contract before any agent implements it.** The
   next decision is public sessions and user-funded inference (#324). ADR-0026
   is accepted as a direction; the session, bootstrap and custody interfaces in
   `docs/research/public-auth-byok-contract.md` are still Proposed. Until that
   freeze exists, public web business routes correctly return HTTP 503
   (`apps/web/src/lib/deployment-mode.ts`, ADR-0027). Do not weaken that guard
   to demo a signed-in user.
5. **Decide provider direction (#195).** ADR-0012 is Proposed. Explicit-key
   OpenAI generation (#328) and embeddings (#329) are merged libraries and are
   not called from `apps/api` or `workers`. Accept or reject ADR-0012 before
   anyone wires a live provider. There is no owner-key fallback.
6. **Name the hosted targets before anyone claims #61 or #108 done.** #61
   bulk-review p95 on the shared local Docker VM was 4,147.19 ms, 1,002.23 ms,
   then 1,501.91 ms against a 1,000 ms limit (`docs/handoff/STATUS.md`,
   `apps/api/EXTRACTION_LOAD.md`). #108 has local preparation and no hosted
   run. Provision the database target and the Railway web/API/worker plus
   shared storage target, or say explicitly that those issues stay blocked.
   Credential names only, never values (`docs/handoff/CREDENTIALS.md`).

## After the lead freezes the next slice

Do not start these in parallel with each other. `packages/contracts/**` and
`db/migrations/**` have one owner at a time. Cap active packages at four. Each
slice needs an issue, a branch from `workstreams.yaml`, and allowed paths.

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
- M1 ingestion, including the HTTP host allowlist, decoded size cap, and
  per-attempt deadline from #345 (`470ef51`), and since #354 the retrieval
  receipts, explicit FRED gaps and named source clocks of ADR-0029/0030/0031.
  Nothing persists receipts yet; that is forecast storage (#66).
- M2 retrieval, claims, and Search Observatory. Mock Recall@10 is 0.4692
  against a 0.90 live gate. That gap is #177 / #201, not a broken mock.
- M3 extraction runtime, review API, and approved-record history. Every
  proposal still requires human review.
- Offline calibration validator (#340) and weighted PAV `isotonic-v1` (#339,
  depth bound in #351). Neither is wired into proposal scoring.
  `workers/src/fel_workers/extraction/isotonic.py` must stay unimported by the
  dataset package, and the reverse.
- `packages/calculation-engine` (formula AST, cyclic groups, Decimal). Nothing
  in `apps/api`, `apps/web`, or `workers` imports it. The 3D desk graph from
  #350 is a fixture schematic, not an integration. The M4 UI and forecast
  packages are unbuilt. `workers` forecasting is an empty placeholder.

Canonical tasks still unchecked, for the lead's planning pass only: `T0112`,
`T0215`, `T0306`, `T0307`, `T0308`, `T0309`, `T0310`, `T0401`–`T0410`,
`T0501`–`T0505`, `T0507`–`T0513`, `T0214b`. `T0308`, `T0309`, and
`T0401`–`T0403` are bare unchecked titles. Those lines do not say that code
has merged or that acceptance evidence is missing, so there is no sentence
there to read before treating the box as open. `T0411` and `T0412` are the
lines that carry an acceptance sentence, and those boxes are checked.
`T0211`–`T0213` and `T0506` are deferred post-MVP.

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
| ADR-0029/0030/0031 have no lead authorization record | Treating receipts as a settled contract for #66 | Lead posts that record on #354, or the Status lines return to Proposed and the index and research note follow |
| `workstreams.yaml` status drift | Safe dispatch | Lead ledger edit. Agents do not flip status |

## Do not

- Do not edit `specs/001-financial-evidence-lab/tasks.md` checkboxes in an implementation pull request.
- Do not deploy API and worker with different local storage directories. Citations will resolve and the bytes will not.
- Do not lower Recall@10, the 1,000 ms review budget, or the 0.85/0.80 review thresholds to make a gate pass.
- Do not use a shared server bearer in the public Next.js app as a stand-in for a user.
- Do not put credential values in issues, commits, logs, fixtures, or this file.
