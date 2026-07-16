# Benchmark seed questions (EXT-1, issue #71)

**Status: delivered.** `questions.jsonl` contains 65 candidate benchmark
questions, each grounded in SEC EDGAR filings fetched during authoring. SEC
EDGAR egress is now enabled for the authoring session (the earlier checkpoint
was blocked purely by a session egress restriction that has since been
lifted); every accession, value, unit, period, and verbatim quote in the
dataset was copied from bytes fetched this session through a shared,
rate-limited SEC fetch helper (global <= 2 req/s, compliant `User-Agent`
with contact info).

## Deliverable summary

- **Questions:** 65 (target 60-100).
- **Distinct issuers:** 16 of the canonical 20-issuer cohort.
- **Categories:** all ten represented, each with >= 5 questions.
- **Integrity:** every answerable question carries >= 1 evidence entry whose
  `quote` is present **byte-for-byte** in the fetched filing document; every
  unanswerable (`insufficient_evidence`) question sets
  `expected_answer: null`, leaves `evidence` empty, and lists the real
  accession(s) actually reviewed in `documents_reviewed`.

### Category counts

| category | count |
|---|---|
| exact_fact_lookup | 12 |
| guidance_extraction | 8 |
| revenue_driver_extraction | 7 |
| filing_section_retrieval | 6 |
| table_reasoning | 6 |
| insufficient_evidence | 6 |
| contradiction_detection | 5 |
| multi_period_comparison | 5 |
| temporal_cutoff_trap | 5 |
| restatement_handling | 5 |
| **total** | **65** |

### Issuer coverage (16 of 20)

Covered: MDB, CRM, NOW, DDOG, ZS, SNOW, OKTA, TWLO, HUBS, DOCU, ZM, TEAM,
BILL, PD, ESTC, WDAY.

Not yet covered (4): FIVN, APPF, PCTY, PAYC — see Known gaps.

## Methodology

- **Source of truth:** SEC EDGAR only. Filing accessions are taken from each
  issuer's `https://data.sec.gov/submissions/CIK{10-digit}.json`; documents
  are resolved through the Archives filing index
  (`.../Archives/edgar/data/{cik}/{accession-nodash}/index.json`) and the
  primary exhibit is fetched directly.
- **Primary documents:** most questions are grounded in earnings press
  releases furnished as **Exhibit 99.1** to Form 8-K (Item 2.02). These
  releases contain revenue, segment/product drivers, guidance ranges,
  customer metrics, and margin data in quotable narrative form. Restatement
  questions are grounded in BILL Holdings' Form 10-K/A (FY2022) and Form
  10-Q/A (Q1 FY2023).
- **Verbatim-quote rule:** because EDGAR HTML wraps figures in tags and
  encodes spaces as `&#160;`, quotes were selected as contiguous, tag-free
  spans of the raw document bytes. An automated build step re-fetches each
  cited document and asserts every `quote` is a byte-exact substring before
  the JSONL is emitted; any quote that fails is trimmed or dropped. Numbers
  drawn from financial-statement tables (e.g., Snowflake's income statement)
  are quoted as the exact cell tokens that appear in the fetched bytes.
- **Trap construction (grounded, not synthetic):**
  - *temporal_cutoff_trap* — `as_of` is set to a date **before** a
    subsequently issued guidance revision, so the correct answer is the
    earlier, then-current guidance. Both the then-current filing and the
    later revising filing are listed in `documents_reviewed`. Examples: MDB
    and CRM full-year guidance raised in the following quarter; NOW Q1 2026
    subscription guidance superseded by actuals; HubSpot FY2026 guidance
    raised.
  - *contradiction_detection* — two filings (or, for Snowflake, a single
    sentence stating current vs previous guidance) report different figures
    for the same metric/period; the expected answer reconciles them by
    timing (a raise, or guidance-vs-actual) rather than flagging a genuine
    error.
  - *restatement_handling* — BILL's FY2022 10-K/A discloses a genuine
    retrospective recast from early adoption of ASU 2021-08 (increasing
    acquired deferred revenue and goodwill for the Invoice2go acquisition;
    goodwill recast from $2,354,812K to $2,363,090K). A companion question
    tests the distinction that BILL's Q1 FY2023 10-Q/A amended internal
    controls **without** restating the financial statements.
- **Typed answers:** numeric answers use
  `{"kind":"numeric","value","unit","scale","period"}` (ranges are expressed
  as `"low-high"` in `value`, e.g. `"2.92-2.96"`); narrative answers use
  `{"kind":"text","text"}`; unanswerable questions use `null`.
- **Adjudication:** every record has `adjudication.status = "draft"` with an
  empty `reviewers` list. Human adjudication happens later (T0214a/T0214b).

## Validation

Run from the repository root:

```
python3 - <<'PY'
import json, collections
REQUIRED = {"exact_fact_lookup","filing_section_retrieval","multi_period_comparison",
 "table_reasoning","guidance_extraction","revenue_driver_extraction","contradiction_detection",
 "temporal_cutoff_trap","restatement_handling","insufficient_evidence"}
cat = collections.Counter(); n = 0
for line in open("evals/datasets/benchmark-seed/questions.jsonl"):
    line = line.strip()
    if not line: continue
    r = json.loads(line); n += 1
    cat[r["category"]] += 1
    assert r["as_of"].endswith("Z"), r["id"]
    if r["answerable"]:
        assert r["expected_answer"] is not None, r["id"]
        assert any(e.get("accession") and e.get("quote") for e in r["evidence"]), r["id"]
    else:
        assert r["expected_answer"] is None, r["id"]
        assert len(r["documents_reviewed"]) >= 1, r["id"]
assert n >= 60, n
for c in REQUIRED: assert cat[c] >= 5, (c, cat[c])
print("OK", n, "questions;", "categories:", dict(cat))
PY
```

## Known gaps

- **Four cohort issuers uncovered:** FIVN, APPF, PCTY, PAYC. Their filings
  are reachable, but 16 issuers already exceed the >= 12 coverage target;
  these four are the natural next additions if the set is expanded toward
  100 questions.
- **Restatement concentration:** all five `restatement_handling` questions
  are grounded in BILL Holdings' FY2022 10-K/A and Q1 FY2023 10-Q/A, the
  clearest genuine recast/amendment in the cohort during the reviewed
  window. Broadening this category to additional issuers (e.g., via
  XBRL `companyconcept` prior-period recasts) is a good follow-up.
- **Answer scaling conventions:** guidance ranges are encoded as
  `"low-high"` strings in the numeric `value` field. If T0214a/T0214b prefer
  discrete `low`/`high` numeric fields, a small schema migration will be
  needed; the underlying quotes already capture both endpoints verbatim.
- **iXBRL structural traps:** these questions target disclosed values and
  narrative; parser-stress structural fixtures (nested/rotated tables,
  iXBRL continuations) are the province of EXT-2, not this dataset.
