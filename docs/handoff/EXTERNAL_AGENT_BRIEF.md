# External agent brief — parallel preparation work

**Audience:** the external agent currently reviewing PR #69 (and any other
Git-capable agent joining the project).
**Issued:** 2026-07-12 by the integration flow.
**Read first:** `AGENTS.md`, `CLAUDE.md`, `docs/handoff/README.md`,
`docs/handoff/STATUS.md`, `docs/handoff/workstreams.yaml`.

## Why this brief exists

The main implementation line is strictly serial right now:
PR #69 (`M0-INFRA-CI`) → `M0-CONTRACTS` (#52) → `M0-PLATFORM` (#53). Those
packages are owned by the primary implementation agent — do not start them.

The three work items below are **deliberately chosen to have zero dependency
on any merge and zero path overlap** with the M0/M1 code packages. They
produce artifacts the M1–M3 packages will consume, so finishing them early
shortens the critical path later. All three can proceed immediately and in
parallel with each other.

## Ground rules (non-negotiable)

1. Base every branch on `integration/m0`. One work item = one branch = one PR.
2. Stay inside the allowed paths listed per item. Never edit shared paths
   (`.github/**`, `.specify/**`, `specs/**`, `packages/contracts/**`,
   `db/migrations/**`, `docs/decisions/**`, `docs/handoff/workstreams.yaml`)
   or any file under `apps/`, `workers/`, `packages/`, `infra/`.
3. Mock-first: no credentials anywhere. SEC EDGAR fetches must set a
   compliant `User-Agent` with contact information and respect the published
   rate limits (max 10 req/s; be far more conservative).
4. Open a draft PR early; fill in `.github/PULL_REQUEST_TEMPLATE.md`; push
   bounded checkpoints; keep each PR under ~600 changed lines where feasible
   (data files are exempt but keep individual files small — see item 2).
5. CI (`.github/workflows/ci.yml`, once PR #69 merges) must stay green. None
   of these items should touch code, so only `format:check` is likely to
   apply — run `make ci` locally anyway before pushing.
6. Do not mark Spec Kit tasks complete and do not edit `workstreams.yaml` or
   `STATUS.md`; the integration lead links your merged outputs into the
   queue.

## Issuer cohort (use for all three items)

Pick 20 US-listed B2B SaaS issuers with at least 8 years of filing history
where possible. Suggested starting set (adjust with rationale if a name lacks
history or fits poorly): CRM, NOW, WDAY, TEAM, HUBS, ZS, OKTA, DDOG, MDB,
SNOW, TWLO, ZM, DOCU, PD, ESTC, FIVN, APPF, PCTY, PAYC, BILL. Record the
final cohort with CIKs in your first PR; the same cohort must be used
consistently across items.

---

## EXT-1 — Benchmark seed questions (feeds T0214a / T0214b)

- **Branch:** `agent/ext-benchmark-seed`
- **Allowed paths:** `evals/datasets/benchmark-seed/**`
- **Deliverable:** 60–100 candidate benchmark questions as JSONL, plus a
  README describing methodology and coverage.

Spec references: `specs/001-financial-evidence-lab/spec.md` sections 19.5
(categories and phasing) and 10.3 (temporal fields). Cover all ten
categories — exact fact lookup, filing-section retrieval, multi-period
comparison, table reasoning, guidance extraction, revenue-driver extraction,
contradiction detection, temporal cutoff traps, restatement handling,
insufficient-evidence cases — with at least 5 questions each.

One JSON object per line in `questions.jsonl`:

```json
{
  "id": "BM-0001",
  "category": "temporal_cutoff_trap",
  "issuer": {"ticker": "MDB", "cik": "0001441816"},
  "question": "As of 2023-06-01, what full-year revenue guidance had management most recently issued?",
  "as_of": "2023-06-01T00:00:00Z",
  "expected_answer": "…",
  "evidence": [
    {"accession": "0001441816-23-000123", "form": "10-Q", "section": "MD&A", "quote": "…"}
  ],
  "answerable": true,
  "difficulty": "medium",
  "author_notes": "Trap: revised guidance was issued after the cutoff.",
  "adjudication": {"status": "draft", "reviewers": []}
}
```

Rules: every `expected_answer` must be verifiable from the cited public
filing (include the exact quote); `as_of` is mandatory; for
insufficient-evidence cases set `"answerable": false` and explain why in
`author_notes`; numeric answers carry value, unit, scale, and period.
`adjudication.status` stays `draft` — human adjudication happens later
(T0214a/T0214b).

**Acceptance:** JSONL parses line-by-line; ≥60 questions; ≥5 per category;
every question cites at least one accession number; README documents cohort,
category counts, and known gaps.

---

## EXT-2 — SEC golden-file fixture manifest (feeds T0103 / T0111)

- **Branch:** `agent/ext-sec-fixtures`
- **Allowed paths:** `evals/datasets/sec-fixtures/**`
- **Deliverable:** a curated manifest of parser-stressing SEC filings, plus
  small excerpt samples. **Do not commit full filing documents** — they
  bloat the repository; the M1 ingestion package will fetch full bytes from
  the manifest.

`manifest.jsonl`, one filing per line:

```json
{
  "id": "FX-0001",
  "issuer": {"ticker": "CRM", "cik": "0001108524"},
  "form": "10-K",
  "accession": "0001108524-24-000012",
  "filed_at": "2024-03-06",
  "primary_document": "crm-20240131.htm",
  "url": "https://www.sec.gov/Archives/edgar/data/1108524/000110852424000012/crm-20240131.htm",
  "sha256": "…",
  "why_selected": "Multi-level nested segment tables; iXBRL continuation facts.",
  "stress_features": ["nested_tables", "ixbrl_continuation", "amended_later"]
}
```

Target 40–60 filings across the cohort, deliberately over-sampling the ugly
cases: amended filings (10-K/A), restatements, fiscal-year changes, nested
and rotated tables, multi-currency disclosures, unusual scale markers
("in thousands, except per-share"), iXBRL continuations and dimensional
facts, and at least three pre-2018 filings with older formatting. For up to
10 of them, include a short representative excerpt (< 50 KB each) under
`excerpts/` showing the tricky structure, with source URL and byte range
noted in a comment header.

**Acceptance:** manifest parses; every URL resolves at authoring time;
sha256 recorded for every entry; ≥8 distinct `stress_features` values
represented; README explains selection methodology and how M1 should consume
the manifest.

---

## EXT-3 — B2B SaaS disclosure ontology research (feeds T0301)

- **Branch:** `agent/ext-ontology-research`
- **Allowed paths:** `docs/research/ontology/**`
- **Deliverable:** a research report (`saas-disclosure-survey.md`) mapping
  how the cohort actually discloses the metrics the M3 ontology must model:
  ARR/annualized revenue run-rate, NRR/GRR (and their definitional
  variants), customer counts and thresholds ($100k+ customers), seats/users,
  bookings, billings, calculated billings, RPO/cRPO, deferred revenue, and
  gross-margin splits (subscription vs services).

For each metric: which issuers disclose it, where (press release vs 10-K/10-Q
section), under what exact label, with what definition variants, whether it
is XBRL-tagged or narrative-only, and citation (accession + section) for at
least three issuer examples. Conclude with: (a) a proposed normalized metric
list with unit/period semantics for the T0301 ontology, (b) the top ten
definitional conflicts an extractor must disambiguate, and (c) which metrics
are reliably XBRL-derivable versus extraction-only.

**Acceptance:** every claim cites a real filing (accession + section); covers
≥15 of the 20 cohort issuers; conflicts section is concrete (issuer A defines
NRR as X, issuer B as Y); ends with the machine-consumable proposed metric
table.

---

## Coordination and handoff

- The primary agent's active paths right now: PR #69
  (`.github/workflows/**`, `db/**`, `infra/**`), then `packages/contracts/**`
  (M0-CONTRACTS) and the M0-PLATFORM path set. Your three items touch none
  of these. If you believe you need a path outside your allowed list, stop
  and raise it on your PR instead of editing.
- Order of usefulness if you must serialize: EXT-2 (fixtures unblock M1
  test-writing) → EXT-1 (benchmark) → EXT-3 (ontology).
- On completion, leave each PR in review state with the template filled in;
  the integration lead merges and records the artifacts in the queue. If
  blocked, push the branch with a checkpoint and describe: failing step,
  attempted remedies, and exact next action.
