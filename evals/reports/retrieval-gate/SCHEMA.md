# Retrieval-gate report schema (`retrieval-gate-report/v1`)

Reports in this directory are produced by `evals/harness/retrieval_gate.py`
(issue #201), the executable release gate over
`fel_retrieval_evals.metrics`. Each run builds (or reuses, when
content-identical) a small synthetic corpus + index version, runs every
question in the benchmark seed through the real `fel_retrieval` planner ->
lanes -> fusion pipeline (mock embedding provider), grades the run, and
writes one JSON file per run. Determinism is the load-bearing property: an
unchanged seed always reuses the same corpus/index rows and produces a
byte-identical `gate` / `not_evaluable` / `questions` / `per_question`
section — only `meta` (timestamps, the resolved database URL) varies run to
run. `evals/tests/test_retrieval_gate.py` asserts exactly this by running the
CLI twice against a live database and diffing the graded section.

## Why a synthesized corpus, not the live SEC corpus

The seed's evidence cites real EDGAR filings; a credentialed live
corpus/provider is tracked separately (issue #177) and is not wired up here.
Building against it would either fabricate a corpus that happens to contain
the golden quotes (indistinguishable from cheating) or grade against nothing
at all. Instead, this harness builds one small Postgres document per cited
accession whose text *is* the golden quote(s) from that accession's
evidence — the literal strings `fel_retrieval_evals.compile` resolves
offsets against — so Recall@10 and the cutoff guard are graded against real,
code-run retrieval output rather than an assumption.

## Gates computed vs. `not_evaluable`

This pipeline is retrieval-only: planner + lanes + fusion, never claim or
citation generation (that is `apps/api`'s generation stage). Of the five
`fel_retrieval_evals.metrics.SMOKE_THRESHOLDS` gates:

| Gate | Status | Basis |
|---|---|---|
| `recall_at_10` | **computed** | Gold ids are the deterministic item ids (`fel_retrieval.ids.item_id`) of the passages built from each answerable question's own evidence quotes. Unanswerable (negative) questions vacuously pass — there is no gold to find. |
| `temporal_validity` | **computed** | True for a question when every one of its fused candidates carries `published_at <= as_of` — the same cutoff guard `fel_retrieval.lanes` enforces in SQL, checked here from the pipeline's actual output. |
| `numeric_accuracy` | not evaluable | Requires a generated numeric claim; none exists without a generation stage. |
| `entailment_precision` | not evaluable | Requires generated claims + citations to grade for entailment; none exist. |
| `citation_completeness` | not evaluable | Requires rendered claims to check for citations; none exist. |

The three not-evaluable gates are reported (with a zero support count and a
reason) under `not_evaluable` and **never** affect `gate.passed` or the
process exit code — the harness fails closed only on gates it actually
measured, and never fabricates a label for one it did not.

## Top-level fields

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | Always `"retrieval-gate-report/v1"`. |
| `gate` | object | `fel_retrieval_evals.metrics.GateReport.to_dict()`, computed over only `temporal_validity` and `recall_at_10`. See below. |
| `not_evaluable` | object | Keyed by metric name (`numeric_accuracy`, `entailment_precision`, `citation_completeness`); each value is `{"reason": string, "support": int}`. `support` is always `0` here (population is `metric_supports`'s denominator for that metric). |
| `questions` | object | `{"total": int, "evaluated": int, "excluded": [...]}`. `excluded` lists any manifest entry whose gold evidence could not be resolved in the synthetic corpus (expected to be empty; the harness's own corpus is built from that entry's evidence, so an exclusion signals a bug rather than a benchmark gap). |
| `per_question` | array | One diagnostic object per evaluated question, sorted by `id` (see below). |
| `meta` | object | Run metadata — timestamps, resolved database, corpus/index identity. Excluded from the determinism contract; everything else in the report is not. |

### `gate` (from `GateReport.to_dict()`)

- `passed` (bool) — AND of every result in `results`.
- `results` (array of `{name, value, threshold, passed}`) — one entry per
  computable gate (`recall_at_10`, `temporal_validity`), sorted by name.
  `value`/`threshold` are 4-decimal-place strings (exact `Decimal`, never a
  float). `passed` requires both `value >= threshold` **and** a nonzero
  support (population) for that metric, per
  `fel_retrieval_evals.metrics.build_gate_report`'s fail-closed rule.
- `reranker` — `{triggered, trigger_threshold, note}`, the ADR-0002
  report-only cross-encoder trigger decision (baseline Recall@10 < 90%).

### `per_question[i]`

| Field | Type | Notes |
|---|---|---|
| `id` | string | Seed question id (e.g. `"BM-0001"`). |
| `category` | string | Seed category. |
| `answerable` | bool | From the compiled manifest entry. |
| `gold_count` | int | Number of gold passage item ids for this question (`0` for a negative case). |
| `retrieved_count` | int | Number of fused candidates returned for this question. |
| `recall_at_10` | string | This question's `question_recall_at_10`, 4-decimal string. |
| `temporal_ok` | bool | Whether every fused candidate satisfied the cutoff for this question. |

### `meta`

`database` (redacted — no credentials), `provider` (always `"mock"` today),
`embedding_model`, `questions_path` (repo-relative), `questions_sha256`,
`corpus_version_id`, `index_version_id`, `index_reused` (bool — whether this
run resumed an already-published index rather than building it),
`item_count`, `generated_at` (ISO-8601, UTC).

## Exit codes

- `0` — every computable gate passed.
- `1` — at least one computable gate failed (`gate.passed` is `false`).
- `2` — could not run at all: `--provider live` (not provisioned, see #177),
  no database URL, psycopg missing, or the synthetic corpus fixture itself
  failed to compile/resolve (a harness bug, not a benchmark result) —
  nothing is written. Only `--provider mock` is implemented.
