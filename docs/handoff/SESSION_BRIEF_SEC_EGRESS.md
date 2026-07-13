# Session brief — SEC egress execution

**Audience:** the Claude Code cloud session started after the environment's
network allowlist was changed to Custom (`www.sec.gov`, `data.sec.gov`,
`efts.sec.gov` + package managers) on 2026-07-13.
**Issued by:** the integration flow (session `claude/repo-analysis-g0fvjy`).
**Read first:** `AGENTS.md`, `CLAUDE.md`, `docs/handoff/STATUS.md`,
`docs/handoff/EXTERNAL_AGENT_BRIEF.md` (contains the full acceptance
criteria for every item below — this brief does not repeat them).

Your job in this session: verify SEC egress, then **execute the three
parked EXT work items** on their existing branches so their checkpoint PRs
become completed deliverables. You are an executor, not the integration
lead: do not merge anything, and do not edit `workstreams.yaml` or
`STATUS.md`.

## Step 0 — verify egress before anything else

```sh
for h in www.sec.gov data.sec.gov efts.sec.gov; do curl -sI "https://$h/" | head -1; done
```

Expected: an HTTP status line per host (200/301/403-from-SEC are all fine —
any HTTP response proves the tunnel opened). Failure mode: a proxy CONNECT
denial (check `curl -sS "$HTTPS_PROXY/__agentproxy/status"` for
`connect_rejected` / `x-deny-reason: host_not_allowed`).

**If any host is still blocked: STOP.** Report to the user that the policy
did not bind (likely causes: the environment edit wasn't saved, this
session was started in a different environment, or it was started before
the save). Do not use mirrors, caches, Wayback, or training recall as a
substitute — that violates the integrity rules below.

## Non-negotiable rules (carried over from the standing contract)

1. **SEC fair access:** every request sets
   `User-Agent: financial-evidence-lab research (sordidsunday@icloud.com)`
   and stays far below SEC's 10 req/s limit — self-cap **≤2 req/s total
   across the whole session**. If you parallelize agents, split that budget
   (e.g. two fetching agents at ≤1 req/s each); the cap is global, not
   per-agent. Back off exponentially on 429/403.
2. **Never fabricate evidence.** Every accession number, quote, sha256,
   URL, and filing fact you commit must come from bytes actually fetched
   this session. If something can't be verified, record the gap instead.
3. **No credentials anywhere.** These items need none (SEC requires only
   the User-Agent). Do not add FRED/Alpha Vantage keys or any secret.
4. **Stay inside each item's allowed paths** (listed below). The canonical
   cohort `evals/datasets/issuer-cohort.json` is read-only; propose cohort
   changes on the PR instead of editing it.
5. **Reuse the existing branches and PRs.** Push to the same branch so the
   existing PR updates; do not open new PRs or new branches.
6. `make ci` must pass before every push (data-only changes still run the
   full gate). Validate JSONL line-by-line (`python3 -c` with `json.loads`
   per line) and re-verify recorded sha256 values against fetched bytes.

## The three work items (independent — run in parallel if you wish)

Each branch already contains a committed methodology README written when
the work was parked. **Execute that methodology unchanged**; the READMEs
plus `docs/handoff/EXTERNAL_AGENT_BRIEF.md` are the specification.

| Item | Branch | PR | Refs | Allowed paths | Methodology |
|---|---|---|---|---|---|
| EXT-2 SEC fixture manifest | `agent/ext-sec-fixtures` | #76 | #72 | `evals/datasets/sec-fixtures/**` | `evals/datasets/sec-fixtures/README.md` |
| EXT-1 benchmark seed | `agent/ext-benchmark-seed` | #74 | #71 | `evals/datasets/benchmark-seed/**` | `evals/datasets/benchmark-seed/README.md` |
| EXT-3 ontology survey | `agent/ext-ontology-research` | #75 | #73 | `docs/research/ontology/**` | `docs/research/ontology/README.md` |

Priority if you must serialize: **EXT-2 → EXT-1 → EXT-3** (fixtures unblock
M1 test-writing first). EXT-2 and EXT-1 are fetch-heavy; EXT-3 is mostly
reading filings you will already have fetched — consider running EXT-3 last
and reusing EXT-2's fetched documents to stay under the rate budget.

Key acceptance reminders (full criteria in the brief):

- **EXT-2:** 40–60 manifest entries over-sampling ugly filings, sha256 for
  every entry recorded from actually-fetched bytes, ≥8 distinct
  `stress_features`, ≤10 small excerpts (<50 KB) — never full filings.
- **EXT-1:** ≥60 questions, ≥5 per each of the ten categories, every
  answerable question carries a real accession + exact verifying quote;
  unanswerable questions list every filing actually checked.
- **EXT-3:** every claim cites accession + section, ≥15 of 20 cohort
  issuers covered, ends with the machine-consumable proposed metric table.

## Per-item workflow

1. `git fetch origin <branch> && git checkout <branch>` (use a dedicated
   worktree per item if running in parallel).
2. Rebase onto `origin/main` only if the branch conflicts with main;
   otherwise leave history as-is.
3. Execute the committed methodology; commit in bounded checkpoints with
   clear messages.
4. Run `make ci` + the item's data validation; push to the same branch
   (`git push -u origin <branch>`).
5. Update the PR body: replace the "blocked checkpoint" framing with
   completed acceptance evidence per `.github/PULL_REQUEST_TEMPLATE.md`,
   keeping `Refs #7x`. Leave the PR **in review — do not merge or mark
   anything merged**; the integration lead records artifacts in the queue.

## If blocked

Leave the branch buildable, push a checkpoint, and document on the PR: the
failing command, relevant output, attempted remedies, required decision or
credential, and the exact next action. Report the same to the user.

## Optional stretch goal (only after all three EXT items are done)

A read-only live smoke of the M1 ingestion SEC client: check out
`agent/m1-ingestion` (PR #80) in a scratch worktree, and from a throwaway
script (in the session scratchpad, never committed) instantiate
`workers/src/fel_workers/ingestion/sec_client.py::LiveSecClient` against
real EDGAR for one issuer from the cohort — verify submissions JSON and one
document fetch succeed under the rate cap. Report the result as a comment
on PR #80. No code changes, no commits.

## Definition of done for this session

- Egress verified (or a clear STOP report if not).
- PRs #74, #75, #76 updated from blocked checkpoints to completed
  deliverables with green CI, real fetched evidence, and filled-in
  acceptance sections — left in review state.
- A final summary to the user: per-item artifact counts, validation
  results, rate-limit adherence, any gaps recorded, and (if attempted) the
  PR #80 live-smoke outcome.
