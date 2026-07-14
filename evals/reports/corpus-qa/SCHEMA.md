# Corpus-QA report schema (`corpus-qa-report/v1`)

Reports in this directory are produced by the T0112 harness
(`evals/harness/corpus_qa.py`), which drives the REAL discovery → fetch →
ingest pipeline (`fel_workers.consumer.run_worker`) over the canonical
benchmark cohort `evals/datasets/issuer-cohort.json` (read-only) and then
measures corpus quality from the tables the pipeline itself wrote. One
JSON file per run, named `<label>.json`; the schema is validated by
`harness.corpus_qa.validate_report` (fails closed) and exercised by
`evals/tests/test_corpus_qa_harness.py`.

## Provenance modes

- `"mode": "synthetic"` — NO network. A deterministic mock `SecClient`
  (`evals/harness/synthetic_sec.py`) serves fabricated filings rendered
  from the committed templates in `evals/datasets/synthetic-corpus/`.
  Cohort tickers/CIKs key benchmark slots only; **no metric in a
  synthetic report describes any real company's filings**, and the
  `provenance_note` states so. The synthetic plan deliberately includes
  duplicate presentations, a restating amendment for every 5th issuer,
  and two classes of corrupt documents so the quarantine and linkage
  metrics measure real code paths.
- `"mode": "live"` — real EDGAR fetches through the frozen
  `LiveSecClient` (SEC fair-access compliant). Requires SEC egress.

## Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | Always `"corpus-qa-report/v1"`. |
| `schema_version` | int | Always `1` for this schema. |
| `mode` | string | `"synthetic"` or `"live"` (see above). |
| `label` | string | Run label; also the report's file name stem. |
| `generated_at` | string | ISO-8601 UTC timestamp of report creation. |
| `provenance_note` | string | Human-readable synthetic/live disclosure. |
| `cohort` | object | `path`, `sha256` (of the cohort file bytes), `as_of`, `issuer_count`. Pins exactly which cohort revision was measured. |
| `pipeline` | object | `parser_version`, `normalizer_version`, `queue`, `jobs_completed` (jobs the consumer completed in this run; `0` on a pure re-measure). |
| `issuers` | array | One metrics object per cohort issuer (below), in cohort order. |
| `totals` | object | The per-issuer fields summed, plus `span_hash_verification_rate` recomputed over the totals and `quarantine_reason_distribution` (reason code → count across all issuers). |

## Per-issuer metrics object

| Field | Type | Meaning |
| --- | --- | --- |
| `ticker`, `cik` | string | Cohort slot key (from `issuer-cohort.json`). |
| `entity_id` | string | Deterministic entity UUID (`entity_id_for_cik`). |
| `documents_ingested` | int | `documents` rows for the entity (includes quarantined-only documents, which the corpus API hides). |
| `documents_parsed` | int | Documents with ≥ 1 `parsed` document version (the M1 evidence-visibility gate). |
| `documents_quarantined` | int | Distinct accessions with quarantine entries. |
| `document_versions_parsed` | int | Parsed `document_versions` rows. |
| `facts_total` | int | All `financial_facts` rows for the entity. |
| `facts_canonical` | int | Facts with `duplicate_of IS NULL`. |
| `facts_duplicate` | int | Duplicate presentations collapsed onto a canonical row. |
| `facts_restated` | int | Facts carrying a `restates` link to a superseded prior fact. |
| `spans_total` / `spans_verified` | int | Persisted source spans, and how many re-verified: the span's `text_hash` recomputed from the persisted canonical text slice matches. |
| `span_hash_verification_rate` | string | `spans_verified / spans_total` as an exact decimal STRING (six places; `"1"` when there are no spans). Never a binary float. |
| `quarantine_reasons` | object | Reason code → count for this issuer's quarantined accessions. |

## Regenerating the committed synthetic report

Any disposable Postgres with `db/migrations/0001` + `0002` applied works:

```sh
TEST_DATABASE_URL="postgresql://..." \
PYTHONPATH=evals:workers/src:packages/providers:apps/api \
.venv/bin/python -m harness.corpus_qa \
    --mode synthetic --reset-corpus \
    --reports-dir evals/reports/corpus-qa --label <YYYY-MM-DD>-synthetic-cohort
```

The run is deterministic (same cohort file + templates ⇒ same metrics);
only `generated_at`, `label`, and `jobs_completed` vary between runs.

## Live 20-issuer run (T0112 follow-up; needs SEC egress)

This session had no SEC egress, so the committed acceptance artifact is
the synthetic run. The live run is executed from an egress-enabled
session with the EXACT command below (fair-access identification is
already built into `LiveSecClient`); commit the resulting report next to
the synthetic one:

```sh
FEL_DATABASE_URL="postgresql://<target-db>" \
PYTHONPATH=evals:workers/src:packages/providers:apps/api \
.venv/bin/python -m harness.corpus_qa \
    --mode live \
    --storage-dir /var/fel/storage \
    --forms 10-K,10-Q,10-Q/A \
    --reports-dir evals/reports/corpus-qa --label <YYYY-MM-DD>-live-cohort
```

Never run live mode from CI or an egress-blocked environment, and never
hand-edit a report: reports are generated artifacts, and fabricating
real-issuer numbers is prohibited.
