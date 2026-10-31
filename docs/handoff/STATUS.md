# Implementation status

## October 31 current state

Snapshot base: `main` @ `3808f3b` (#360, merged 2026-10-31). Re-query GitHub
before dispatch; issue and PR states below were read on 2026-10-31. Sections
dated September 16 and earlier are in the
[archived status history](../archive/handoff/STATUS-history-2026-09.md); they
are evidence history, not current state. The October 27 remaining-work snapshot
is [archived](../archive/handoff/2026-10/remaining-work-2026-10-27.md); every
open item from it is carried below or marked closed. Its standing guidance (what is
already on `main` and must not be rebuilt, the unchecked canonical tasks, and
its "Do not" list) was not copied here and still applies; read it in the
archived snapshot.

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

None of these wires calibration into proposal scoring, binds a live model,
or establishes hosted #61 or #108 acceptance. `isotonic.py` and the dataset
package stay mutually unimported.

### Integration-lead decisions and open items

Items 1–6 are the "Needs the integration lead" list of the October 27 snapshot,
in its order. Items 7–9 are later decisions.

| # | Item | State | Evidence or next action |
| --- | --- | --- | --- |
| 1 | ADR-0029/0030/0031 status | Resolved: Proposed | #360 (merged 2026-10-31) returned all three to Proposed, superseding the lead record posted on #354 on 2026-10-29 (#363 decision D8). Re-accepting any of them needs a new authorization record on a PR and a Status line that quotes it. |
| 2 | Reconcile the handoff ledger | Resolved 2026-10-31 | Under #363 slice S3, `workstreams.yaml` records `OFFLINE-CALIBRATION-DATASET` (#340), `OFFLINE-ISOTONIC-CALIBRATOR` (#339, #351) and `DOCS-EXECUTIVE-ARCHITECTURE` (#342) as merged, closes `BACKLOG-EXECUTION-CONTROL` (its staged packages have all merged), and this section replaces the September 16 history. |
| 3 | Close or re-scope issues whose code is on `main` | Open | #336 and #341 are closed. #337 is still open although #339 and #351 implement it: lead closes it. #96 and #87 stay open only as #108 trackers. #61 stays open on its 25-user load gate. |
| 4 | Freeze public sessions and user-funded inference (#324) | Open | ADR-0026 is an accepted direction; the interfaces in `docs/research/public-auth-byok-contract.md` are still Proposed. Public business routes keep returning 503 (ADR-0027); do not weaken that guard to demo a signed-in user. |
| 5 | Provider direction (#195) | Open | ADR-0012 stays Proposed. Per #363 D4 it gains an amendment (S4) recording that its live-provider revisit trigger fired; the Arm A/B benchmark is still the ratify-or-withdraw event. OpenAI adapters #328/#329 are not called from `apps/api` or `workers`. There is no owner-key fallback. |
| 6 | Name hosted targets for #61 and #108 | Open | #61 bulk-review p95 was 4,147.19, 1,002.23 and 1,501.91 ms against 1,000 ms on a shared local VM. #108 has no hosted run. Both stay blocked until the lead provisions the database and Railway/shared-storage targets. Credential names only, never values ([`CREDENTIALS.md`](CREDENTIALS.md)). |
| 7 | ADR-0014 status (#363 D4) | Decided, recording in flight | Accepted effective #247 (`75fad38`); ADR-0032 records it in S4. |
| 8 | Hosted extraction worker (#363 D6) | Blocked | #362 adds a `--queue extraction` Railway service once #62 binds a live model. Until then the API refuses run creation with 503 `EXTRACTION_NOT_CONFIGURED` and inserts no job unless `FEL_ALLOW_MOCK_LLM` is set (`apps/api/app/extraction/runs.py`). |
| 9 | Benchmark seed vs T0214a (#363 D7) | Decided | No ledger change; S1 rewords the benchmark-seed README. |

### Dependency order

Do not start these in parallel. `packages/contracts/**` and `db/migrations/**`
have one owner at a time; cap active packages at four. Each slice needs an
issue, a `workstreams.yaml` branch and allowed paths.

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
| ADR-0012 Proposed | Wiring a live model provider | Lead accepts or rejects #195 after the Arm A/B benchmark |
| No user-owned credential store | Billable provider calls | #324 custody, then #191 accounting |
| #61 load gate unmet | Checking T0308/T0309, starting #62 | Dedicated database target, same workload, no threshold change |
| #108 hosted smoke not run | Closing the production reader path | Railway target, shared storage, lead-provisioned credentials |
| Live corpus and retrieval gates | T0112, T0215, release section 19.6 | #177 after credentials and the embeddings choice |
| Human labels for calibration | T0306/T0310 | #62 after #61 and a real adjudication set; synthetic fixtures are not that set |
| No live model bound for extraction | Hosted extraction runs (#362) | #62, then the #362 Railway service |
| Calculation engine not integrated | M4/M5 product | #64 after #62; do not import the engine from a UI mock and call it done |

Resolved since the October 27 snapshot: the ADR-0029/0030/0031 status
question (item 1, settled as Proposed by #360) and `workstreams.yaml` status
drift (item 2).

### Documentation work in flight

[#363](https://github.com/wilsonhj/financial-evidence-lab/issues/363) tracks
the documentation drift remediation (`DOCS-DRIFT-REMEDIATION`). Plan:
[`2026-10-28-documentation-drift-remediation.md`](../superpowers/plans/2026-10-28-documentation-drift-remediation.md).

- S1 + S2, docs corrections and the first archive pass: #364, open, branch
  `claude/trusting-brahmagupta-8vvgwi`.
- S3, the ledger refresh that wrote this section and archived the
  September/October handoff files: branch `claude/docs-drift-s3-ledger`,
  stacked on #364.
- S4, ADR-0032 recording D4/D5/D7 and the ADR/spec status lines: branch
  `claude/docs-drift-s4-adr0032`.

Canonical task checkboxes, credential policy and release thresholds are
unchanged. No paid inference call was made.
