# EXT executor brief v2 — git-only workflow

**Audience:** the EXT executor session spawned by the integration lead
(2026-07-14, second attempt). You have **no GitHub API tools** — work
entirely through git (clone is pre-authenticated). Everything you need is
in this file plus the repo; report progress by **pushing commits**, never
by PR comments.

## Protocol (do these first, in order)

1. **Status heartbeat (before anything else):** create branch
   `agent/ext-executor-status` from main; commit a file
   `STATUS.md` on it containing the UTC time, "started", and your session
   marker; push. Update + push this file at every milestone below and at
   least hourly while working. This is how the integration lead observes
   you; silence again means this attempt also failed.
2. **Claim check:** `git fetch origin`; if any of the branches
   `agent/ext-sec-fixtures`, `agent/ext-benchmark-seed`,
   `agent/ext-ontology-research`, `agent/m1-corpus-qa` has commits dated
   after 2026-07-14T03:00Z that you did not make, STOP and record why in
   the status file.
3. **Egress check (Step 0):** verify HTTPS to `www.sec.gov`,
   `data.sec.gov`, `efts.sec.gov` per
   `docs/handoff/SESSION_BRIEF_SEC_EGRESS.md`. If blocked, push the exact
   proxy output to the status file and STOP. Never use mirrors or recall.

## Standing rules

Compliant User-Agent `financial-evidence-lab research
(sordidsunday@icloud.com)`; **≤ 2 req/s TOTAL** across everything; every
accession/quote/sha256/URL you commit must come from bytes fetched in THIS
session; never merge; never edit `docs/handoff/workstreams.yaml` or
`docs/handoff/STATUS.md`; `make ci` green before every push; stay inside
each item's allowed paths.

## Work items, in order

### 1. EXT-2 acceptance round — branch `agent/ext-sec-fixtures`
Integration-lead rulings (previously PR #76 comments, restated here as
canonical):
- **8th stress feature:** add a deterministic byte/regex detector for at
  least one of `parenthesized_negatives`, `dash_as_zero`,
  `ixbrl_nil_facts` over the fetched primary documents; tag truthfully;
  restore the validation gate to `>= 8`. If honest detection over all 60
  documents finds none of the three, record that evidence in the README
  and status file and move on — the integration lead will amend the brief.
- **Excerpts:** commit up to 10 representative excerpts (< 50 KB each)
  under `evals/datasets/sec-fixtures/excerpts/` — at minimum one each of:
  iXBRL continuation, dimensional facts, legacy pre-2018 HTML,
  multi-currency, unusual scale markers, one amendment — each with a
  comment header: source URL, exact byte range, full document sha256 from
  the manifest.
- **Deterministic validator:** commit `validate.py` beside the manifest —
  offline checks: id/accession/url/sha256 uniqueness, cohort membership
  against `evals/datasets/issuer-cohort.json`, URL↔accession consistency,
  per-feature re-detection where offline-detectable; plus an optional
  rate-limited online mode (re-fetch + re-hash a sample). The old inline
  gate provably passed duplicate accessions and non-cohort CIKs — the
  validator must not.
- **Amendment provenance:** add `original_accession` (+ URL, + sha256
  where fetched) to all ten `/A` entries.
- **Metadata:** move the contact email out of the dataset README into
  env-var documentation (`FEL_SEC_USER_AGENT` assembly).
- **LAST:** retarget/rebase the branch onto current `main`, re-run the
  validator + `make ci`, push.

### 2. EXT-1 egress spot-checks — branch `agent/ext-benchmark-seed`
The dataset passed full offline verification (11/11). Only egress checks
remain (sampling; budget-light):
- The six `insufficient_evidence` questions (BM-0056..0061): confirm each
  claimed-absent metric is absent from the cited 8-K AND from the
  corresponding 10-Q before `as_of`. Fix any falsified entries.
- Byte-verify quotes for ~10 sampled questions incl. the filing-agent
  accessions (MDB/DDOG under 0001628280, HUBS under 0001193125).
- Confirm the 24 distinct accessions exist with claimed forms/dates.
- Record results in the README verification section; rebase onto `main`;
  push.

### 3. EXT-3 corrections — branch `agent/ext-ontology-research`
Offline verification passed countable bars; corrections required:
- **Scan the four never-cited issuers for real** (APPF, FIVN, PAYC,
  PCTY): latest 10-K MD&A + earnings releases. FIVN "Dollar-Based
  Retention Rate" and PCTY/PAYC annual revenue-retention rates plausibly
  exist — add them (cited) to the relevant families, or document their
  genuine absence with documents reviewed.
- Cite-or-remove the ~13 uncited issuer-specific claims (F7 "Also OKTA,
  TEAM, APPF…", "as do MDB, FIVN, PCTY", the F1 negative claims, ZS
  renewal-assumption, SNOW services-gross-loss, F7 "most issuers").
- Fix the Family-7 roll call (names SNOW/DDOG/ZM/TEAM without RPO cites).
- Correct README self-claims; commit provenance artifacts
  (`sec_fetch.sh`, `provenance.jsonl`, byte-presence re-verification)
  into `docs/research/ontology/`.
- Egress spot-checks: sampled quote byte-presence, post-cutoff figures,
  the 0001193125 filer-counter plausibility, re-run the 120
  companyconcept probes and diff against Part 3.
- Rebase onto `main`; push.

### 4. T0112 live corpus run — branch `agent/m1-corpus-qa` (merged; push a NEW branch `agent/t0112-live-report` from main)
Follow `evals/reports/corpus-qa/SCHEMA.md` exactly: fresh dedicated
database (`createdb fel_corpus_qa_live`, migrations 0001+0002), then the
live harness command with `FEL_SEC_USER_AGENT`, `--mode live`,
`--storage-dir`, `--reports-dir evals/reports/corpus-qa --label
<YYYY-MM-DD>-live-cohort`. Requirements: exit 0, report
`acceptance.accepted: true`, `span_hash_verification_rate: "1.000000"`.
Commit ONLY the report JSON on the new branch and push. If the run fails,
commit the failure report + status notes instead — never edit metrics.

### 5. Issue #81 (EXT-2b supplemental cohort) — only after item 1.
Scope is in the issue body (restated: 3–6 non-cohort issuers selected
from fetched EDGAR evidence — item-4.02 8-Ks, 10-KT/QT filers — appended
as clearly-marked supplemental entries; same fetch-verify pipeline).

## Definition of done
All status-file milestones pushed; branches rebased onto main with green
CI; the live report branch pushed. The integration lead handles all PR
state, comments, and merges.
