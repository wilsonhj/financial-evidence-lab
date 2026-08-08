# Eval report renderers

Stdlib-only, byte-deterministic renderers for committed evaluation reports.
Issue #151 (`EVALS-REPORT-RENDER`); spec:
`docs/research/evals-report-renderer-proposal.md`.

## `corpus_qa_render` — corpus-QA report → Markdown + SVG

Turns **one** `corpus-qa-report/v1` JSON artifact (or its
`corpus-qa-failure/v1` sibling) into a human-readable Markdown summary and a
hand-written SVG bar chart. Input schema:
`evals/reports/corpus-qa/SCHEMA.md`.

```sh
PYTHONPATH=evals .venv/bin/python -m reporting.corpus_qa_render \
    evals/reports/corpus-qa/2026-07-14-synthetic-cohort.json \
    --out-dir /tmp/fel-render
```

Writes `<report-stem>.md` and `<report-stem>.svg` into `--out-dir`. The
output stem comes from the **input file name**, never from the report's own
`label` field, so nothing inside a report can steer where bytes land.

`PYTHONPATH=evals` alone is the whole import path. Contrast the harness
recipe (`SCHEMA.md`), which needs
`evals:workers/src:packages/providers:apps/api` — that difference is the
stdlib-only proof. This tool opens no database and no socket.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Rendered. A **failure report renders successfully too**: it produces Markdown, no SVG, and a one-line note on stderr. |
| 2 | Refusal: unreadable path, malformed JSON, non-object document, or a schema this tool does not render. One line on stderr, nothing written, no traceback. |

The schema gate is fail-closed and accepts exactly two shapes:
`corpus-qa-report/v1` **with `schema_version == 1`**, and
`corpus-qa-failure/v1`. Dispatch is on the `schema` field, never on the
filename — a failed run writes the failure schema to the *same*
`<label>.json` path. The renderer does **not** reimplement
`harness.corpus_qa.validate_report`; deep structural and provenance
validation stays owned by the harness. It also never *imports* the harness
at runtime: `harness.corpus_qa` pulls in `psycopg`, `fel_providers` and
`fel_workers` at module top, which would drag a database driver into a
file-in/file-out tool. The four schema constants are duplicated instead, and
a test-time drift guard asserts they still equal the harness's.

## Determinism contract

Rendering the same input twice, on any machine, on any day, produces
byte-identical Markdown and SVG. This is enforced, not hoped for:

- **No wall clock, no randomness.** `datetime`, `time`, `uuid`, `random` and
  `os` are not imported at all. The only timestamp in the output is
  `generated_at`, copied verbatim from the input.
- **No hash-order iteration.** The two string-keyed maps whose order the
  schema does not fix — `totals.quarantine_reason_distribution` and
  `pipeline.jobs.terminal_counts` — are iterated in `sorted()` key order.
- **Meaningful order is input order.** `issuers`, `run.expected_issuers` and
  acceptance `reasons` render exactly as recorded: cohort order, never value
  order. No sorting, no ranking, no "worst first".
- **No float reaches the output.** Counts are `int`;
  `span_hash_verification_rate` is an exact six-place decimal *string* and is
  echoed verbatim — never parsed to `float`, never re-rounded, never turned
  into a percentage. Every SVG coordinate is computed with integer
  arithmetic and floor division, so no float `repr` can vary.
- **String values are code-fenced** in tables. That is what keeps `cik`
  zero-padding (`0001108524`) and the rate's trailing zeros intact through a
  downstream Markdown renderer or a spreadsheet paste. `|` is escaped as
  `\|` and newlines/tabs are collapsed to spaces inside cells;
  `provenance_note` is emitted as a blockquote instead, so it survives
  intact.
- **Committed goldens.** `evals/tests/golden/corpus-qa/` holds the exact
  expected bytes for both outputs, and the tests assert byte-equality
  against them. The SVG golden is deliberately committed rather than proved
  by a render-twice assertion: render-twice only proves determinism *within
  one process*, whereas the golden also catches cross-version serialization
  drift — e.g. an interpreter that stops preserving `ET.tostring` attribute
  insertion order, which is the one behaviour this SVG serialization depends
  on (verified on CPython 3.11, `.python-version`).

**Regenerating the goldens** (only ever alongside a deliberate, reviewed
change to the renderer):

```sh
PYTHONPATH=evals .venv/bin/python -m reporting.corpus_qa_render \
    evals/reports/corpus-qa/2026-07-14-synthetic-cohort.json \
    --out-dir evals/tests/golden/corpus-qa
```

## n = 1 is a hard design constraint

The repository contains **exactly one** committed corpus-QA report, so there
is **no time series**. Accordingly this tool:

- takes exactly one report per invocation. There is no `--compare`, no glob,
  no directory scan, no multi-report aggregation;
- emits no trend line, delta, sparkline, "change since" or run-over-run
  arrow. A second data point does not exist, and inventing one would be a
  fabricated finding;
- charts only *across issuers within the single snapshot*, which is exactly
  what one observation supports.

A multi-report view is deferred until at least two reports are committed —
realistically the deferred live T0112 cohort run (`SCHEMA.md`, "Live
20-issuer run").

## The `unavailable` sentinel

When an issuer has `spans_total == 0`, `span_hash_verification_rate` is the
literal string `"unavailable"`: an empty denominator is never reported as
`1`. The renderer prints that token as-is — never `0.000000`, never `100%`,
never an em dash, never an empty cell. It computes **no** derived rate of
its own; it only echoes `totals.span_hash_verification_rate` as given, so an
`unavailable` issuer can never contribute to a summary figure.

In the chart, an affected row is marked with `*` in its label and a footnote
is added. Its bar is still drawn — from the integer document counts, which
are always present — so a missing *rate* can never render as a zero-height
or full-height *bar*.

The one committed report exercises none of this (all 20 issuers have
`spans_total > 0` and rate `1.000000`), so coverage comes from an in-memory
fixture in the test module. Reports are generated artifacts: none is ever
hand-edited or fabricated (`SCHEMA.md`, "Regenerating the committed
synthetic report").

## Chart scales

Issuer rows share one axis whose maximum is the largest per-issuer
`documents_ingested`, floored at 1 so an empty or all-zero report cannot
divide by zero. The **TOTAL row is drawn below a separator on its own
scale** and reads as a whole-cohort composition, not as a magnitude
comparable to the issuer rows: the cohort total is an order of magnitude
larger than any single issuer, so putting it on the shared axis would
overflow the plot, and putting the issuers on a totals-sized axis would
flatten every one of them to a few pixels. The separator, the row caption
and the SVG `<desc>` all state which scale is which, and the absolute count
is printed at the end of every bar regardless.

## Failure reports

A `corpus-qa-failure/v1` input renders a Markdown-only summary: a `RUN
FAILURE` banner, the `failure_reason`, every acceptance reason, the shared
provenance fields, and the jobs summary **only when it is non-null**
(`not accounted` otherwise — the schema allows `jobs_completed` and `jobs`
to be `null`). **No SVG is written**, and the CLI says so on stderr: there
are no metrics to chart, and an empty or all-zero chart that could read as
"0 problems" is a defect, not a graceful degradation. Exit code is 0 —
rendering a failure report is a successful render.

## `# nosec B405`

`import xml.etree.ElementTree` trips bandit's `B405` blacklist, which warns
about *parsing* untrusted XML. This module only ever **builds** an element
tree and serializes it; it never parses, so the XXE / decompression-bomb
class the rule guards against is unreachable. The suppression is an inline
`# nosec B405` with the justification on the preceding comment lines —
bandit reads prose on the pragma line itself as test ids and emits warning
noise. Adding `skips` to `[tool.bandit]` in `pyproject.toml` was explicitly
rejected: that is a shared-path edit, and it would blind the entire
repository to B405 forever.

## Known gap: not in CI's mypy dir-list

CI and the Makefile run `mypy` against `evals/graders`, not `evals/`
broadly, so `evals/reporting/**` is **not** type-checked in CI today —
exactly as `evals/harness/**` is not. The module is fully annotated and
passes `mypy` under the repository's `strict = true`:

```sh
.venv/bin/mypy evals/reporting
```

Widening that dir-list is a shared-path change in `pyproject.toml`,
`Makefile` and `.github/workflows/ci.yml`, owned by the integration lead and
out of scope for this package.
