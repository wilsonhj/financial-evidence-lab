# Benchmark seed questions (EXT-1, issue #71) — CHECKPOINT: BLOCKED

**Status: blocked — no `questions.jsonl` is committed yet.** This checkpoint
documents why, per the repository blocked-work protocol (`AGENTS.md`,
`CLAUDE.md`). Nothing in this directory is a deliverable yet.

## Why there is no data in this checkpoint

EXT-1 carries an absolute integrity rule: every accession number, quote,
value, unit, and period in `questions.jsonl` must be copied from SEC EDGAR
content actually fetched during the authoring session. In this session all
outbound web egress is blocked by organization policy, so **zero** filings
could be fetched and therefore **zero** questions could be verified.
Authoring questions from model memory would violate the integrity rule, so
none were authored.

## Failing commands and outputs

All commands used the SEC-compliant header
`User-Agent: financial-evidence-lab research (sordidsunday@icloud.com)`.

1. `curl https://data.sec.gov/submissions/CIK0001441816.json`
   → `curl: (56) CONNECT tunnel failed, response 403` (egress proxy refused
   the CONNECT; per the environment's proxy documentation this means the
   destination host is not on the session's egress allowlist and must be
   reported, not worked around).
2. `curl https://www.sec.gov/` and `curl https://efts.sec.gov/`
   → same `CONNECT tunnel failed, response 403`.
3. WebFetch tool on `https://data.sec.gov/submissions/CIK0001441816.json`,
   `https://www.sec.gov/cgi-bin/browse-edgar?...`,
   `https://www.sec.gov/files/company_tickers.json`,
   `https://efts.sec.gov/LATEST/search-index?...`,
   `https://www.sec.gov/Archives/edgar/data/1441816/`
   → `HTTP 403 Forbidden` for every URL.
4. WebFetch tool on a neutral control URL (`https://example.com/`)
   → `HTTP 403 Forbidden`, confirming the block is session-wide egress
   policy, not SEC rate limiting or User-Agent rejection.
5. The proxy's documented diagnostic endpoint
   (`$HTTPS_PROXY/__agentproxy/status`) was denied by the session's
   permission policy, so per-host allowlist state could not be inspected
   further; the proxy README's guidance for CONNECT 403 applies.

## Attempted remedies

- Retried across all three SEC hosts (`www.sec.gov`, `data.sec.gov`,
  `efts.sec.gov`) and multiple endpoint styles (submissions JSON, Archives
  directory listing, full-text search, browse-edgar) — all 403.
- Tried both permitted access paths named in the work order (curl through
  the configured proxy with the CA bundle, and the WebFetch tool) — both
  blocked.
- Did **not** attempt mirrors or third-party copies of EDGAR content: the
  proxy policy explicitly forbids routing around egress denials, and
  non-canonical sources could not satisfy the quote/accession verification
  requirement anyway.

## Required decision / credential

One of:

- Add `www.sec.gov`, `data.sec.gov`, and `efts.sec.gov` to this session
  environment's egress allowlist (no credentials needed — these are public,
  unauthenticated endpoints), or
- Re-dispatch EXT-1 to an environment with outbound HTTPS access to SEC
  EDGAR.

## Exact next action

Re-run EXT-1 in an environment where
`curl -H "User-Agent: financial-evidence-lab research (<contact email>)"
https://data.sec.gov/submissions/CIK0001441816.json` succeeds. The planned
methodology below is ready to execute unchanged.

## Planned methodology (ready to execute once unblocked)

- **Source of truth:** SEC EDGAR only — submissions JSON for filing
  indexes, Archives filing-index pages to confirm each accession, and
  press-release exhibits (EX-99.1) / R*.htm financial-statement exhibits
  for verbatim quotes. Rate-limited to ≤2 requests/second with a compliant
  User-Agent.
- **Issuers:** only the canonical 20-issuer cohort in
  `evals/datasets/issuer-cohort.json` (read-only), targeting ≥12 distinct
  issuers.
- **Volume and coverage:** 60–100 questions, ≥5 in each of the ten
  categories from `docs/handoff/EXTERNAL_AGENT_BRIEF.md` §EXT-1: exact
  fact lookup, filing-section retrieval, multi-period comparison, table
  reasoning, guidance extraction, revenue-driver extraction, contradiction
  detection, temporal cutoff traps, restatement handling,
  insufficient-evidence cases.
- **Schema:** one JSON object per line in `questions.jsonl`, exactly as
  specified in the brief — typed `expected_answer`
  (`{"kind":"numeric","value":…,"unit":…,"scale":…,"period":…}` or
  `{"kind":"text","text":…}`), mandatory `as_of`, `evidence` entries with
  accession + form + section + exact quote for every answerable question,
  `expected_answer: null` plus non-empty `documents_reviewed` for
  unanswerable ones, `adjudication.status: "draft"`.
- **Verification loop per question:** (1) accession taken from the
  issuer's submissions JSON, (2) independently confirmed by fetching the
  Archives filing-index page, (3) quote extracted verbatim from the fetched
  exhibit, (4) re-verified with a second targeted fetch of the same
  document before inclusion. Any question failing any step is dropped, not
  approximated.
- **Validation before push:** line-by-line `json.loads`; assert ≥60 lines,
  ≥5 per category, every answerable line has ≥1 evidence entry with
  accession + quote, every unanswerable line has non-empty
  `documents_reviewed` and null `expected_answer`.

## Known gaps

All of the deliverable, for the reason above. No cohort gaps can be
assessed until filings are reachable.
