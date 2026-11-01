# Implementation status

## October 31 current state

Snapshot base: `main` @ `c3d6f2f` (#365, merged 2026-10-31). The table below
was first written against `1e414ff` (#364) and omitted #366, which had already
merged at `e91610c`. Re-query GitHub before dispatch; issue and PR states
below were read on 2026-10-31. Sections
dated September 16 and earlier are in the
[archived status history](../archive/handoff/STATUS-history-2026-09.md); they
are evidence history, not current state. The October 27 remaining-work snapshot
is [archived](../archive/handoff/2026-10/remaining-work-2026-10-27.md); every
open item from it is carried below or marked closed. Its standing guidance (what
is already on `main` and must not be rebuilt, and its "Do not" list) is copied
into [Standing guidance](#standing-guidance) below; the archived snapshot is
history, not a source of truth.

### Merged since September 16

Squash merges on `main` after #338 (`437ce55`), oldest first. "Refs" means the
issue is cited but was not closed by the merge.

| SHA | PR | Closes | Outcome |
| --- | --- | --- | --- |
| `950c486` | #343 | — | Extraction review admits TLS-terminated origins; hardened SSE stream framing (#288 review) |
| `2ca7c7b` | #347 | — | Cleared published dependency advisories in both lockfiles |
| `b9c3189` | #339 | Refs #337 | Deterministic weighted PAV `isotonic-v1` calibrator, offline only |
| `bc0435b` | #340 | Refs #336 | Strict offline calibration dataset validator; #336 closed by hand on 2026-10-24 |
| `470ef51` | #345 | — | Ingestion HTTP: per-adapter host allowlist, decoded size cap, per-attempt deadline |
| `167ab22` | #342 | #341 | Executive architecture brief and source-linked system design |
| `275cee6` | #348 | — | ADR index, agent entry point and docs CI checks |
| `59bbf7e` | #349 | — | Docs made findable; stale facts corrected |
| `bd96e63` | #353 | — | Shared-path check diffs from the merge-base, not `base.sha` |
| `f9db6f3` | #352 | Refs #336 | Calibration dataset boundary tests (#340 review follow-up) |
| `12c380a` | #351 | Refs #337 | Isotonic nesting bound and #339 review test gaps |
| `195443c` | #354 | — | FRED and market provenance: receipts, explicit gaps, source clocks (ADR-0029/0030/0031) |
| `da66969` | #355 | — | ADR-0010 Amendment 1 refreshes premises; status stays Proposed |
| `d79eb42` | #350 | — | Editable SVG architecture diagrams and fixture 3D/2D lineage visualizations |
| `9cd1854` | #358 | — | `msgpack` 1.2.4 in the dev lock (CVE-2026-114613) |
| `f7fad6e` | #357 | — | Remaining-work snapshot for agents and the integration lead |
| `f4b1197` | #359 | — | Closed the snapshot's five "Do now" items: shared-path renames and non-ASCII paths, FRED date/value parsing, temporal-suite gap timing, ADR-0010 Amendment 1 corrections, fixture copy in the Desk and Observatory |
| `3808f3b` | #360 | — | ADR-0029/0030/0031 returned to Proposed; shared-path check counts a just-added label; `minimatch` advisory (GHSA-g3hv-75wg-m249) pinned and allowlisted until 2026-12-01 |
| `2b11db9` | #361 | — | `PreToolUse` path guard for Claude Code edits (`scripts/agent/path_guard.py`); asks before shared-path or out-of-lane edits |
| `1e414ff` | #364 | — | #363 S1+S2: drifted docs corrected against code; July EXT briefs and superseded research archived |
| `e91610c` | #366 | — | ADR-0032: ADR-0014 accepted effective #247; ADR-0012 Amendment 1; spec and README status corrections |
| `c3d6f2f` | #365 | — | STATUS.md and workstreams.yaml refreshed; September history archived |

None of these wires calibration into proposal scoring, binds a live model,
or establishes hosted #61 or #108 acceptance. `isotonic.py` and the dataset
package stay mutually unimported.

### Integration-lead decisions and open items

Items 1–6 are the "Needs the integration lead" list of the October 27 snapshot,
in its order. Items 7–9 are later decisions.

| # | Item | State | Evidence or next action |
| --- | --- | --- | --- |
| 1 | ADR-0029/0030/0031 status | Resolved: Proposed | #360 (merged 2026-10-31) returned all three to Proposed, superseding the lead record posted on #354 on 2026-10-29 (#363 decision D8). Re-accepting any of them needs a new authorization record on a PR and a Status line that quotes it. |
| 2 | Reconcile the handoff ledger | Resolved 2026-10-31 | Under #363 slice S3, `workstreams.yaml` records `OFFLINE-CALIBRATION-DATASET` (#340), `OFFLINE-ISOTONIC-CALIBRATOR` (#339, #351) and `DOCS-EXECUTIVE-ARCHITECTURE` (#342) as merged, closes `BACKLOG-EXECUTION-CONTROL` as a control package (the remaining waves #62, #64-#68 and #324 continue in their own packages), and this section replaces the September 16 history. These status flips and the `DOCS-DRIFT-REMEDIATION` registration are authorized by an integration-lead authorization record on PR #365 under #363 decisions D1 and D2, not by an ADR. |
| 3 | Close or re-scope issues whose code is on `main` | Open | #336 and #341 are closed. #337 is still open although #339 and #351 implement it: lead closes it. #96 and #87 stay open only as #108 trackers. #61 stays open on its 25-user load gate. |
| 4 | Freeze public sessions and user-funded inference (#324) | Open | ADR-0026 is an accepted direction; the interfaces in `docs/research/public-auth-byok-contract.md` are still Proposed. Public business routes keep returning 503 (ADR-0027); do not weaken that guard to demo a signed-in user. |
| 5 | Provider direction (#195) | Open | ADR-0012 stays Proposed. Amendment 1 (2026-10-31), merged in #366 (`e91610c`), records that its live-provider revisit trigger fired; the Arm A/B benchmark is still the ratify-or-withdraw event. OpenAI adapters #328/#329 are not called from `apps/api` or `workers`. There is no owner-key fallback. |
| 6 | Name hosted targets for #61 and #108 | Open | #61 bulk-review p95 was 4,147.19, 1,002.23 and 1,501.91 ms against 1,000 ms on a shared local VM. #108 has no hosted run. Both stay blocked until the lead provisions the database and Railway/shared-storage targets. Credential names only, never values ([`CREDENTIALS.md`](CREDENTIALS.md)). |
| 7 | ADR-0014 status (#363 D4) | Resolved 2026-10-31 | ADR-0014 is Accepted, effective at #247 (`75fad38`). ADR-0032 records that acceptance and merged in #366 (`e91610c`). |
| 8 | Hosted extraction worker (#363 D6) | Blocked | #362 adds a `--queue extraction` Railway service once #62 binds a live model. Until then the API refuses run creation with 503 `EXTRACTION_NOT_CONFIGURED` and inserts no job unless `FEL_ALLOW_MOCK_LLM` is truthy (`1`, `true`, `yes` or `on`; merely set is not enough), and even then an extraction policy and an active corpus must exist or it returns the same 503 (`apps/api/app/extraction/runs.py`). |
| 9 | Benchmark seed vs T0214a (#363 D7) | Decided | No ledger change; S1 rewords the benchmark-seed README. |

### Dependency order

Do not start these in parallel. `packages/contracts/**` and `db/migrations/**`
have one owner at a time; cap active packages at four. Each slice needs an
issue, a `workstreams.yaml` branch and allowed paths.

```text
#324 public session + BYOK custody
        |
        +--> #292 hosted identity acceptance
        +--> #195 user-bound OpenAI runtime + usage wiring
                |
                +--> #177 live cutover (credentials, embeddings choice, Alpha Vantage budget)
                        |
                        +--> #56 / T0112 live 20-issuer corpus
                        +--> #132 / T0215 live 65-question retrieval gate
                        +--> #191 live usage accounting

#61 load gate on a dedicated database (independent of #324, blocked on a host)
#108 hosted reader smoke (independent of #324, blocked on Railway + shared storage)

#61 load accepted --+--> #62 wire isotonic-v1 + human labels (T0306, T0307, T0310)
#177 live cutover --+    (needs both: M3-CONFIDENCE-GATE depends on M3-REVIEW and
                         RELEASE-LIVE-CUTOVER, hosted credentials; never #61 alone)
        |
        +--> #362 hosted extraction worker service
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

### Known blockers

| Blocker | What it stops | What unblocks it |
| --- | --- | --- |
| No per-user web session | Public business routes return 503 | Lead freezes #324, then an agent implements it |
| ADR-0012 Proposed | Substituting for ADR-0002's model baseline | Benchmark evidence and an accepted substitution ADR. The OpenAI baseline remains accepted; user-bound authorization, durable usage wiring and live acceptance are still required (#324, #195, #177). |
| No user-owned credential store | Billable provider calls | #324 custody, then #191 accounting |
| #61 load gate unmet | Checking T0308/T0309, starting #62 | Dedicated database target, same workload, no threshold change |
| #108 hosted smoke not run | Closing the production reader path | Railway target, shared storage, lead-provisioned credentials |
| Live corpus and retrieval gates | T0112, T0215, release section 19.6 | #177 after credentials and the embeddings choice |
| Human labels for calibration | T0306/T0310 | #62 after #61 and a real adjudication set; synthetic fixtures are not that set |
| No live model bound for extraction | Hosted extraction runs (#362) | #62, then the #362 Railway service |
| Calculation engine not integrated | M4/M5 product | #64 after #62; do not import the engine from a UI mock and call it done |

Resolved since the October 27 snapshot: the ADR-0029/0030/0031 status
question (item 1, settled as Proposed by #360), `workstreams.yaml` status
drift (item 2), and ADR-0014's acceptance record (item 7, ADR-0032 in #366).

### Standing guidance

Carried unchanged from the October 27 remaining-work snapshot. The October 27
list of unchecked canonical tasks is not repeated: read
`specs/001-financial-evidence-lab/tasks.md` for task state.

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

#### Do not

- Do not edit `specs/001-financial-evidence-lab/tasks.md` checkboxes in an implementation pull request.
- Do not deploy API and worker with different local storage directories. Citations will resolve and the bytes will not.
- Do not lower Recall@10, the 1,000 ms review budget, or the 0.85/0.80 review thresholds to make a gate pass.
- Do not use a shared server bearer in the public Next.js app as a stand-in for a user.
- Do not put credential values in issues, commits, logs, fixtures, or this file.

#### Test isolation

Run any new DB-backed suite in #61 or #62 against an isolated `<db>_extraction`
sibling database, not the shared base `TEST_DATABASE_URL` database; see
[Database-backed tests](../development/testing.md#database-backed-tests).

### Documentation work in flight

[#363](https://github.com/wilsonhj/financial-evidence-lab/issues/363) tracks
the documentation drift remediation (`DOCS-DRIFT-REMEDIATION`). Plan:
[`2026-10-28-documentation-drift-remediation.md`](../superpowers/plans/2026-10-28-documentation-drift-remediation.md).

- S1 + S2, docs corrections and the first archive pass: merged as #364
  (`1e414ff`).
- S3, the ledger refresh that wrote this section and archived the
  September/October handoff files: #365, branch `claude/docs-drift-s3-ledger`.
- S4, ADR-0032 recording D4/D5/D7 and the ADR/spec status lines: #366, branch
  `claude/docs-drift-s4-adr0032`.

Canonical task checkboxes, credential policy and release thresholds are
unchanged. No paid inference call was made.
