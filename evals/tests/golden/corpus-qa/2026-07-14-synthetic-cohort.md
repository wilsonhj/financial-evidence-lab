# Corpus QA report: `2026-07-14-synthetic-cohort`

> **SYNTHETIC RUN. NOT AN ACCEPTANCE ARTIFACT: synthetic reports are never acceptance-grade, and no metric below describes any real company's filings.**
>
> Mode: `synthetic`. Accepted: **no**.
>
> SYNTHETIC RUN: the pipeline, queue, quarantine, and metrics paths are real, but every ingested byte was generated from committed synthetic templates (evals/datasets/synthetic-corpus/). Cohort tickers label the benchmark slots in this report ONLY — every database row is keyed by a namespaced synthetic identity, and NO metric in this report describes any real company's filings.

## Provenance

| Field | Value |
| --- | --- |
| `label` | `2026-07-14-synthetic-cohort` |
| `generated_at` | `2026-07-14T03:24:12.286619+00:00` |
| `run.run_id` | `11f525301ba04b468516f2051ba5419a` |
| `run.as_of` | `2026-07-13` |
| `run.identity_namespace` | `fel-corpus-qa-synthetic/v1` |
| `cohort.path` | `evals/datasets/issuer-cohort.json` |
| `cohort.sha256` | `3fda084f60f4fd00225d36e0e6233ac03d0f2ff4420cad1b9d2ef95cf72e4b4c` |
| `cohort.issuer_count` | 20 |
| `pipeline.parser_version` | `fel-parser/1.0.0` |
| `pipeline.normalizer_version` | `fel-xbrl/1.0.0` |
| `pipeline.queue` | `ingestion` |
| `pipeline.jobs_completed` | 70 |
| `run.expected_issuers` | `CRM, NOW, WDAY, TEAM, HUBS, ZS, OKTA, DDOG, MDB, SNOW, TWLO, ZM, DOCU, PD, ESTC, FIVN, APPF, PCTY, PAYC, BILL` |

## Acceptance

Accepted: **no**

- synthetic run: T0112 acceptance requires the deferred LIVE cohort run (no SEC egress in this session); synthetic reports are never acceptance-grade

## Totals

| Metric | Value |
| --- | --- |
| `expected_documents` | 50 |
| `documents_ingested` | 50 |
| `documents_parsed` | 44 |
| `documents_quarantined` | 6 |
| `document_versions_parsed` | 44 |
| `facts_total` | 264 |
| `facts_canonical` | 220 |
| `facts_duplicate` | 44 |
| `facts_restated` | 8 |
| `spans_total` | 572 |
| `spans_verified` | 572 |
| `span_hash_verification_rate` | `1.000000` |

## Per-issuer metrics

Cohort order, exactly as recorded. Not ranked.

| ticker | cik | expected_documents | documents_ingested | documents_parsed | documents_quarantined | facts_total | facts_canonical | facts_duplicate | facts_restated | spans_total | spans_verified | span_hash_verification_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `CRM` | `0001108524` | 3 | 3 | 3 | 0 | 18 | 15 | 3 | 2 | 39 | 39 | `1.000000` |
| `NOW` | `0001373715` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `WDAY` | `0001327811` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `TEAM` | `0001650372` | 3 | 3 | 2 | 1 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `HUBS` | `0001404655` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `ZS` | `0001713683` | 4 | 4 | 3 | 1 | 18 | 15 | 3 | 2 | 39 | 39 | `1.000000` |
| `OKTA` | `0001660134` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `DDOG` | `0001561550` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `MDB` | `0001441816` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `SNOW` | `0001640147` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `TWLO` | `0001447669` | 4 | 4 | 3 | 1 | 18 | 15 | 3 | 2 | 39 | 39 | `1.000000` |
| `ZM` | `0001585521` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `DOCU` | `0001261333` | 3 | 3 | 2 | 1 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `PD` | `0001568100` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `ESTC` | `0001707753` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `FIVN` | `0001288847` | 3 | 3 | 3 | 0 | 18 | 15 | 3 | 2 | 39 | 39 | `1.000000` |
| `APPF` | `0001433195` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `PCTY` | `0001591698` | 3 | 3 | 2 | 1 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `PAYC` | `0001590955` | 2 | 2 | 2 | 0 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |
| `BILL` | `0001786352` | 3 | 3 | 2 | 1 | 12 | 10 | 2 | 0 | 26 | 26 | `1.000000` |

## Quarantine reasons

| Reason | Count |
| --- | --- |
| `UNKNOWN_CONTEXT` | 3 |
| `UNKNOWN_FORMAT` | 3 |

## Jobs

| Field | Value |
| --- | --- |
| `discovery_expected` | 20 |
| `fetch_expected` | 50 |
| `pending` | 0 |
| `terminal_counts` | `succeeded=70` |
| `backlog_after_run` | 0 |
| `missing_fetch_jobs (count)` | 0 |
| `surplus_fetch_jobs (count)` | 0 |
| `stale_fetch_jobs (count)` | 0 |
| `failures (count)` | 0 |
