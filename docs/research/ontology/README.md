# EXT-3 — B2B SaaS disclosure ontology research (issue #73)

**Status: COMPLETE — SEC EDGAR egress enabled this session; survey written.**

The disclosure survey that feeds the T0301 ontology is in
`saas-disclosure-survey.md`. SEC egress (`data.sec.gov`, `www.sec.gov`) is now
allowed for this session, so the prior BLOCKED checkpoint has been replaced with
the real deliverable. All access went through the shared rate-limited helper
`sec/sec_fetch.sh` (global ≤2 req/s lock).

## 1. Completion summary

- **Issuers surveyed rigorously: 20 / 20** (target ≥15). For each: latest 10-K,
  latest 10-Q, most recent 8-K carrying Item 2.02 and its EX-99.1 exhibit, plus
  six XBRL `companyconcept` probes.
- **Per-metric-family citations: ≥3 cited issuer examples each** (target met) for
  all nine families (ARR, NRR/GRR, spend-threshold customer cohorts, seats/users,
  bookings, billings/calculated billings, RPO/cRPO, deferred revenue/contract
  liabilities, subscription-vs-services gross margin).
- **Integrity:** every issuer-specific claim quotes a sentence verbatim from a
  filing fetched and read this session, cited as `CIK / accession / form
  §section`. A 48-claim cross-family sample was re-verified byte-present in the
  cached response bodies (48/48 after HTML normalization).
- **XBRL determination:** `RevenueRemainingPerformanceObligation` tagged for all
  20; deferred revenue/contract liabilities tagged for all 20 but under mixed
  ASC 606 / legacy conventions (recorded per issuer). ARR, NRR/GRR, customer
  counts, seats, bookings, calculated billings are extraction-only (no GAAP
  concept). See `saas-disclosure-survey.md` Part 3.

The methodology that was executed is retained verbatim in section 2 below.

## 2. Survey methodology (executed)

### 2.1 Cohort and coverage target

Canonical cohort: the 20 issuers in `evals/datasets/issuer-cohort.json`
(read-only): CRM, NOW, WDAY, TEAM, HUBS, ZS, OKTA, DDOG, MDB, SNOW, TWLO,
ZM, DOCU, PD, ESTC, FIVN, APPF, PCTY, PAYC, BILL. Coverage target: ≥15 of 20
surveyed rigorously (depth beats breadth), ≥3 cited issuer examples per
metric family, every issuer-specific claim carrying an accession + section
citation, unverifiable cells marked `not surveyed`.

### 2.2 Metric families and source strategy per metric

| # | Metric family | Primary source | Secondary source | XBRL check |
|---|---|---|---|---|
| 1 | ARR / annualized revenue run-rate | 8-K EX-99.1 press-release highlights | 10-K MD&A "Key Business Metrics" (definition text) | expect narrative-only; confirm absence of tags |
| 2 | NRR / GRR and variants | 10-K/10-Q MD&A Key Business Metrics (full definitional paragraph) | 8-K EX-99.1 (headline value) | expect narrative-only |
| 3 | Customer counts / spend-threshold cohorts ($100k+, $1M+) | 10-K/10-Q MD&A Key Business Metrics | 8-K EX-99.1 highlights | expect narrative-only |
| 4 | Seats / users / paid licenses | 10-K MD&A + business section | 8-K EX-99.1 | expect narrative-only |
| 5 | Bookings | 8-K EX-99.1 and MD&A commentary | 10-K MD&A | expect narrative-only |
| 6 | Billings / calculated billings | 8-K EX-99.1 (incl. GAAP-to-non-GAAP reconciliation tables) | 10-Q MD&A | derivable from tagged revenue + deferred-revenue facts; record issuer formula |
| 7 | RPO / cRPO | 10-K/10-Q revenue note (ASC 606 disclosure) | 8-K EX-99.1 (headline) | `us-gaap:RevenueRemainingPerformanceObligation` (+ ExpectedTimingOfSatisfaction axis for cRPO) via companyconcept API |
| 8 | Deferred revenue / contract liabilities | balance sheet + revenue note | 8-K EX-99.1 balance-sheet table | `us-gaap:ContractWithCustomerLiability(Current/Noncurrent)` vs legacy `DeferredRevenue*` tags — record which each issuer uses |
| 9 | Subscription vs services gross margin | income statement disaggregated revenue/cost-of-revenue lines | 8-K EX-99.1 statements | tagged line items with product/service members; margin itself is derived |

Keyword sets for scanning (to be matched case-insensitively, with the full
sentence captured verbatim): "annual recurring revenue", "annualized
recurring revenue", "run-rate"; "net revenue retention", "dollar-based net
retention", "net expansion rate", "net revenue expansion", "gross retention";
"customers with", "$100,000", "$1 million", "total customers", "paying
customers"; "seats", "paid users", "monthly active"; "bookings"; "billings",
"calculated billings"; "remaining performance obligation", "cRPO"; "deferred
revenue", "contract liabilities"; "subscription gross margin", "cost of
subscription", "professional services and other".

### 2.3 Per-issuer procedure

At ≤2 requests/second with
`User-Agent: financial-evidence-lab research (sordidsunday@icloud.com)`:

1. `https://data.sec.gov/submissions/CIK{10-digit}.json` — resolve latest
   10-K, latest 10-Q, and most recent 8-K whose items include 2.02.
2. Fetch the 8-K accession index (`.../Archives/edgar/data/{cik}/{accession-nodash}/index.json`);
   fetch its EX-99.1 exhibit; keyword-scan; record exact label, definition
   sentence, and placement (highlights bullet vs prose vs table).
3. Fetch the 10-K primary document; extract the MD&A "Key Business Metrics"
   (or equivalent) section, revenue-recognition/RPO note, and income-statement
   line labels; record definitional sentences verbatim.
4. XBRL determination via
   `https://data.sec.gov/api/xbrl/companyconcept/CIK{...}/us-gaap/{tag}.json`
   for the tags in the table above; a 404 plus absence of issuer-extension
   tags in the filing's iXBRL confirms narrative-only.
5. Record each finding as: issuer, metric, disclosed? (yes/no/not surveyed),
   location (form + section), exact label (verbatim), definition variant
   (verbatim), XBRL-tagged vs narrative-only, citation.

Citation format: `CIK / accession-number (dashed) / form, section` — e.g.
`0001561550 / 0001561550-25-000025 / 10-K, MD&A — Key Business Metrics`
(illustrative format only; not a verified claim).

### 2.4 Deliverable structure (unchanged from the brief)

`saas-disclosure-survey.md` = per-metric survey (issuers, locations, labels,
definition variants, tagging, ≥3 citations each), then (a) normalized metric
list with unit/period semantics as a machine-consumable markdown table
(fields: metric_id, canonical_name, kind, unit, scale_handling,
period_semantics — point-in-time vs flow vs trailing-window, value_type),
(b) top ten definitional conflicts stated issuer-vs-issuer with verbatim
definitions, (c) XBRL-derivable vs extraction-only split verified per issuer.

## 3. Scope note

Only `docs/research/ontology/**` is touched, per the EXT-3 allowed paths.
The canonical cohort file `evals/datasets/issuer-cohort.json` was read and
not modified.
