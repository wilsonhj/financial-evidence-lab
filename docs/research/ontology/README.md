# EXT-3 — B2B SaaS disclosure ontology research (issue #73)

**Status: BLOCKED — SEC EDGAR is unreachable from this session's network.**

This directory will hold `saas-disclosure-survey.md`, the disclosure survey
that feeds the T0301 ontology. The work item's integrity rule is absolute:
every issuer-specific claim must cite an accession + section actually fetched
and read during the authoring session. No SEC endpoint is reachable from this
session (confirmed independently by the orchestrator and the EXT-1 agent:
all outbound web egress is 403-denied at the gateway), so no issuer claim can
be verified and the survey has not been written. Writing it from training
recall or third-party mirrors would violate the integrity rule and poison
T0301, so this checkpoint contains **zero issuer-specific disclosure claims**.

## 1. Blocker report (per `CLAUDE.md` blocked-work protocol)

### Failing commands and relevant output

1. `curl -sS -H "User-Agent: financial-evidence-lab research (sordidsunday@icloud.com)" https://data.sec.gov/submissions/CIK0001561550.json`
   → `curl: (56) CONNECT tunnel failed, response 403` (same for every cohort CIK).
2. Identical failure for `https://www.sec.gov/cgi-bin/browse-edgar?...`,
   `https://www.sec.gov/Archives/...`,
   `https://efts.sec.gov/LATEST/search-index?...`, and control hosts
   (`https://example.com` also 403 — egress is deny-by-default).
3. WebFetch (harness fetch tool) to the same SEC hosts → HTTP 403; the agent
   proxy's failure log shows the identical gateway CONNECT rejection for those
   requests, so the tool-level 403 is the egress policy, not sec.gov itself.
4. Agent-proxy status endpoint (`/__agentproxy/status`) records, for every
   attempt:
   `{"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "data.sec.gov:443"}`
   and equivalents for `www.sec.gov:443` and `efts.sec.gov:443`. The proxy
   README states a 403 CONNECT means the destination host is not allowed by
   the organization's egress policy for this session and must be reported,
   not routed around.

### Blocked hosts this work item requires

- `data.sec.gov` — submissions JSON; XBRL `companyconcept`/`companyfacts`
  APIs (needed for the XBRL-derivable vs extraction-only determination).
- `www.sec.gov` — Archives: 10-K/10-Q primary documents, 8-K exhibit
  indexes, EX-99.1 earnings press-release exhibits.
- `efts.sec.gov` — full-text search (locating metric phrases per issuer).

### Attempted remedies (all failed or insufficient)

- curl with the proxy CA bundle (`--cacert /root/.ccr/ca-bundle.crt`) and the
  compliant SEC User-Agent — same CONNECT 403 (failure is pre-TLS, at the
  gateway).
- WebFetch for all three SEC hosts — same policy denial at the gateway.
- Consulted the proxy README and status endpoint per the environment's own
  diagnostic instructions — confirmed org-policy denial; routing around it is
  explicitly forbidden.
- WebSearch (server-side, not subject to session egress) does return genuine
  sec.gov Archives URLs, but only search-engine snippets. It cannot retrieve
  full filings, exhibit indexes, section text, or XBRL facts, so it cannot
  meet the accession+section verification bar for ~150 issuer×metric
  determinations. A snippet-sourced survey was deliberately not written.

### Required decision / credential

No credential is required (all endpoints are public). Required: allowlist
`data.sec.gov`, `www.sec.gov`, and `efts.sec.gov` (port 443) in the session
egress policy, or re-dispatch EXT-3 to an environment with SEC egress.

### Exact next action

Re-run EXT-3 with SEC egress, executing the methodology in section 2 below,
and write `docs/research/ontology/saas-disclosure-survey.md` on this branch.
Estimated ~70–90 HTTP fetches at ≤2 req/s (well under EDGAR's 10 req/s cap).

## 2. Ready-to-execute survey methodology

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
