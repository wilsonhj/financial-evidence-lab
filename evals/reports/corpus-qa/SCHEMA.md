# Corpus-QA report schema (`corpus-qa-report/v1`)

Reports in this directory are produced by the T0112 harness
(`evals/harness/corpus_qa.py`), which drives the REAL discovery → fetch →
ingest pipeline (`fel_workers.consumer.run_worker`) over the canonical
benchmark cohort `evals/datasets/issuer-cohort.json` (read-only) and then
measures corpus quality **strictly from this run's outputs**: the harness
lists the run's expected filings up front, records every expected job's
terminal outcome from the queryable `jobs` table, and aggregates metrics
over exactly the run's (entity, accession) set — never over global or
historical table contents. One JSON file per run, named `<label>.json`;
the schema is validated by `harness.corpus_qa.validate_report` (fails
closed, including provenance checks) and exercised by
`evals/tests/test_corpus_qa_harness.py`.

## Provenance modes and identity namespaces

- `"mode": "synthetic"` — NO network. A deterministic mock `SecClient`
  (`evals/harness/synthetic_sec.py`) serves fabricated filings rendered
  from the committed templates in `evals/datasets/synthetic-corpus/`.
  Every database row is keyed by a **namespaced synthetic identity**
  (`identity_namespace: "fel-corpus-qa-synthetic/v1"`): each cohort slot
  gets a deterministic 12-digit synthetic CIK
  (`harness.corpus_qa.synthetic_cik`, uuid5 over a synthetic namespace +
  the slot ticker), from which the entity id, accessions, and fetch-job
  idempotency keys derive. Real normalized CIKs are exactly 10 digits, so
  the synthetic and live identity spaces are disjoint by construction —
  a synthetic run can never collide with a later live run's discovery
  idempotency keys or corpus rows in the same database. Cohort
  tickers/CIKs label the benchmark slots in the REPORT only; **no metric
  in a synthetic report describes any real company's filings**, and the
  `provenance_note` states so. The synthetic plan deliberately includes
  duplicate presentations, a restating amendment for every 5th issuer,
  and two classes of corrupt documents so the quarantine and linkage
  metrics measure real code paths.
- `"mode": "live"` — real EDGAR fetches through the frozen
  `LiveSecClient` (SEC fair-access compliant;
  `identity_namespace: "sec-cik"`, rows keyed by
  `entity_id_for_cik(<cohort CIK>)`). Requires SEC egress AND
  `FEL_SEC_USER_AGENT` (below).

The validator rejects mixed or ambiguous provenance: `run.mode` must
match the report `mode`, the identity namespace must match the mode, and
every issuer's `entity_id` must be exactly the identity that mode
prescribes (synthetic entity id for synthetic reports, cohort-CIK entity
id for live reports).

## Run success vs acceptance

A returning consumer proves nothing — the harness fails the run (nonzero
exit; report still written, marked non-acceptance) when any expected job
is failed/pending/missing or when the iteration budget was exhausted with
a backlog (`pipeline.jobs.backlog_after_run > 0`).

`acceptance.accepted` is `true` only for a LIVE run in which every
expected job succeeded, every expected issuer has ≥ 1 successfully parsed
document, and evidence (source spans) was produced. **Synthetic reports
are never acceptance-grade**: they always carry
`acceptance.accepted: false` with the deferred-live reason, and the
validator rejects a synthetic report claiming acceptance. The committed
synthetic report in this directory is therefore NOT the T0112 acceptance
artifact — T0112 acceptance remains open until the live cohort run is
executed and committed.

## Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | Always `"corpus-qa-report/v1"`. |
| `schema_version` | int | Always `1` for this schema. |
| `mode` | string | `"synthetic"` or `"live"` (see above). |
| `label` | string | Run label; also the report's file name stem. |
| `generated_at` | string | ISO-8601 UTC timestamp of report creation. |
| `provenance_note` | string | Human-readable synthetic/live disclosure. |
| `run` | object | Run provenance: `run_id`, `mode`, `as_of`, `identity_namespace`, `expected_issuers` (cohort tickers, in order). |
| `acceptance` | object | `accepted` (bool) + `reasons` (non-empty when not accepted). See above. |
| `cohort` | object | `path`, `sha256` (of the cohort file bytes), `as_of`, `issuer_count`. Pins exactly which cohort revision was measured. |
| `pipeline` | object | `parser_version`, `normalizer_version`, `queue`, `jobs_completed` (jobs the consumer completed in this run), and `jobs` (per-job terminal outcomes, below). |
| `issuers` | array | One metrics object per cohort issuer (below), in cohort order. |
| `totals` | object | The per-issuer fields summed, plus `span_hash_verification_rate` recomputed over the totals and `quarantine_reason_distribution` (reason code → count across all issuers). |

## `pipeline.jobs` — per-job terminal outcomes

| Field | Type | Meaning |
| --- | --- | --- |
| `discovery_expected` / `fetch_expected` | int | Jobs this run expected: one discovery per issuer; one fetch per filing discovered from the run's submissions listing. |
| `terminal_counts` | object | Status → count over every expected job, read back from the `jobs` table (`succeeded`, `failed`, `queued`, ...). |
| `pending` | int | Expected jobs still `queued`/`claimed`/`running`. Nonzero ⇒ run failure. |
| `missing_fetch_jobs` | array | Discovered accessions with no fetch job in the queue. Non-empty ⇒ run failure. |
| `backlog_after_run` | int | Jobs left undrained in the queue after the iteration budget. Nonzero ⇒ run failure. |
| `failures` | array | One entry per non-succeeded expected job: `job_id`, `kind`, `status`, `accession`, `cik`, `error`. |

## Per-issuer metrics object

All counts are scoped to THIS run's accession set for the issuer (from
the run's own submissions listing) — rows written by earlier runs in the
same database are never aggregated.

| Field | Type | Meaning |
| --- | --- | --- |
| `ticker`, `cik` | string | Cohort slot label (from `issuer-cohort.json`; in synthetic mode this is a report label only, never a DB key). |
| `entity_id` | string | The entity UUID this run's rows are actually keyed by: `synthetic_entity_id(ticker)` in synthetic mode, `entity_id_for_cik(cik)` in live mode. |
| `expected_documents` | int | Filings this run expected for the issuer. |
| `documents_ingested` | int | `documents` rows in the run's accession set (includes quarantined-only documents, which the corpus API hides). |
| `documents_parsed` | int | Documents with ≥ 1 `parsed` document version (the M1 evidence-visibility gate). |
| `documents_quarantined` | int | Distinct run accessions with quarantine entries. |
| `document_versions_parsed` | int | Parsed `document_versions` rows. |
| `facts_total` | int | `financial_facts` rows over the run's parsed versions. |
| `facts_canonical` | int | Facts with `duplicate_of IS NULL`. |
| `facts_duplicate` | int | Duplicate presentations collapsed onto a canonical row. |
| `facts_restated` | int | Facts carrying a `restates` link to a superseded prior fact. |
| `spans_total` / `spans_verified` | int | Persisted source spans, and how many re-verified: the span's `text_hash` recomputed from the persisted canonical text slice matches. |
| `span_hash_verification_rate` | string | `spans_verified / spans_total` as an exact decimal STRING (six places). With zero spans the rate is `"unavailable"` — an empty denominator is NEVER reported as `"1"`. |
| `quarantine_reasons` | object | Reason code → count for this issuer's quarantined run accessions. |

## Regenerating the committed synthetic report

Any disposable Postgres with `db/migrations/0001` + `0002` applied works.
The destructive reset fails closed: it never reads `FEL_DATABASE_URL`,
requires the explicit confirmation flag, and refuses database names not
ending in `_test` unless `FEL_HARNESS_ALLOW_RESET=1` marks the target
disposable — all with exit 2 before any connection.

```sh
TEST_DATABASE_URL="postgresql://.../<name>_test" \
PYTHONPATH=evals:workers/src:packages/providers:apps/api \
.venv/bin/python -m harness.corpus_qa \
    --mode synthetic --reset-corpus --i-know-this-destroys-data \
    --reports-dir evals/reports/corpus-qa --label <YYYY-MM-DD>-synthetic-cohort
```

The run is deterministic (same cohort file + templates ⇒ same metrics);
only `generated_at`, `label`, and `run.run_id` vary between runs.

## Live 20-issuer run (T0112 acceptance; deferred — needs SEC egress)

This session had no SEC egress, so only the synthetic report is
committed and **T0112 acceptance remains open**. The live run is executed
from an egress-enabled session with the EXACT command below.
`FEL_SEC_USER_AGENT` is REQUIRED (non-empty, with an `@` contact marker,
mirroring the worker deployment gate from the infra workstream); the
harness exits 2 before any network access when it is absent or
malformed. Commit the resulting report next to the synthetic one:

```sh
FEL_DATABASE_URL="postgresql://<target-db>" \
FEL_SEC_USER_AGENT="financial-evidence-lab corpus-qa (<ops-contact@example.com>)" \
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

### Known limitation: repeated LIVE runs against one database

The pipeline's discovery handler deduplicates fetch jobs globally per
accession (`sec-fetch|<accession>` in `workers/src`), so a SECOND live
run against the same database will not re-fetch/re-process filings a
prior live run already ingested — those jobs are simply found already
`succeeded`. The harness still reports correctly (outcomes and metrics
are keyed by the run's expected accession set, so the report covers all
of its filings and excludes everything else), but true cross-run
rediscovery scoping (e.g. run-scoped fetch keys or forced re-fetch)
would require changes to the discovery code in `workers/src`, which is
outside this workstream's allowed paths. Flagged for the integration
lead.
