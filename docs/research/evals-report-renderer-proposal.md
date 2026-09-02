# Agent work package — issue draft

**Status: proposal, not an approved work package.** Nothing here is dispatchable
until the integration lead registers `EVALS-REPORT-RENDER` in
`docs/handoff/workstreams.yaml` (a shared path) and opens the issue. This file
is analysis output only; it authorizes no code change and checks no Spec Kit
box. Delete it if the proposal is declined.

Target form: `.github/ISSUE_TEMPLATE/agent-task.yml` (labels: `agent-task`).
Each `##` heading below maps 1:1 to a form field, in form order. Paste
field-by-field.

**Issue title (form `title:` prefix is `"[PACKAGE-ID] "`):**

```
[EVALS-REPORT-RENDER] Stdlib-only corpus-QA eval report renderer (Markdown + SVG)
```

---

## Work package ID

*(form field `package`, `type: input`, required)*

```
EVALS-REPORT-RENDER
```

Proposed new package. **Not yet in `docs/handoff/workstreams.yaml`.** That file
is a shared path (`AGENTS.md:38`, `workstreams.yaml:14`) — the integration lead
must register the entry before dispatch. Suggested entry, matching the existing
schema and the `evals/**`-owning packages around it:

```yaml
  - id: EVALS-REPORT-RENDER
    issue: <this issue>
    tasks: [] # unallocated; no Spec Kit task covers eval-report rendering
    depends_on: [M1-CORPUS-QA]
    team: trust
    branch: agent/evals-report-render
    status: ready
    allowed_paths: [evals/**]
```

`team: trust` matches M1-CORPUS-QA (#56), READER-CROSS-STACK (#96) and
M3-CONFIDENCE-GATE (#62), the other `evals/**` owners.

---

## Spec Kit task IDs

*(form field `tasks`, `type: input`, required)*

```
None — unallocated. No Spec Kit task covers eval-report rendering.
```

**This is a deliberate answer, not an omission.** I read every task in
`specs/001-financial-evidence-lab/tasks.md` (T0001–T0513). Nothing covers
rendering an eval report:

- `T0112` ("Ingest the first 20 benchmark issuers and record corpus-quality
  metrics", `tasks.md:31`) *produces* the JSON this package consumes. It is
  still unchecked — its acceptance needs the deferred **live** cohort run
  (`evals/reports/corpus-qa/SCHEMA.md:207-249`). Rendering does not advance it.
- `T0510` (`tasks.md:88`, "Export Markdown/PDF briefs, CSV/XLSX tables…") is
  the **product** export surface in `packages/export/**`, owned by
  M5-AUDIT-RELEASE (#68). Not eval tooling.
- `T0513` (`tasks.md:92`, "immutable MVP release artifact and signed evaluation
  report") is the M5 release artifact, also #68.
- `T0406`/`T0407` (`tasks.md:71-72`) are the in-product ECharts/React Flow web
  charts in `apps/web/**`. Unrelated.

**Recommended handling — use `tasks: []`.** This is the established repo
precedent for scoped work with no canonical task ID; ten registered packages
already carry `tasks: []` with the scope ruled in the issue body:
M1-COMPANY-FACTS (#83, `workstreams.yaml:184` — commented "unallocated spec
requirement; scoped + ruled in the issue"), READER-CONTRACT (#89),
READER-WEB-OFFSETS (#90), READER-API (#94), READER-WEB-HTTP (#95),
READER-CROSS-STACK (#96), READER-PROD-SMOKE (#108), M2-CONTRACT (#100),
M3-CONTRACT (#101), DB-GUARD-HARDENING (#125).

**If the lead prefers a canonical ID instead:** the next free slot in the M1
section is `T0113` (verified unused — `grep -rn "T0113\|T0114"` returns zero
hits repo-wide). It is offered here as **PROPOSED AND UNALLOCATED ONLY**. The
implementing agent must not use it, must not add it to `tasks.md`, and must not
check any Spec Kit box: `specs/**` is a shared path and "Agents do not mark Spec
Kit tasks complete. The integration lead checks tasks only after merge and
verification" (`AGENTS.md:24`).

---

## Required outcome and acceptance criteria

*(form field `outcome`, `type: textarea`, required)*

### Outcome

A stdlib-only, byte-deterministic renderer that turns one committed
`corpus-qa-report/v1` JSON file into (a) a human-readable Markdown summary and
(b) a hand-written SVG chart, with unit tests. It adds **zero** dependencies and
touches only `evals/**`.

Today the repo has exactly one committed eval report
(`evals/reports/corpus-qa/2026-07-14-synthetic-cohort.json`, 13,190 bytes,
sha256 `4f0458e8df3566649d80851e29665fb51f0e979cc15613f23a606ccf6a7bdd7a`) and
**zero** report-rendering code: no Markdown emitter, no HTML writer, no
`$GITHUB_STEP_SUMMARY` (0 occurrences repo-wide), and no `tabulate` / `rich` /
`jinja2` / `pandas` / `matplotlib` anywhere in `requirements-dev.txt` or
`pyproject.toml`. Reviewing corpus quality means reading 13 KB of raw JSON by
hand.

### Files created (exact paths — this is the whole deliverable)

| Path | Kind | Est. lines |
| --- | --- | --- |
| `evals/reporting/__init__.py` | new package marker + docstring | ~4 |
| `evals/reporting/corpus_qa_render.py` | renderer + CLI | ~280 |
| `evals/reporting/README.md` | usage, determinism contract, n=1 note | ~25 |
| `evals/tests/test_corpus_qa_render.py` | unit tests | ~180 |
| `evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.md` | generated golden | ~40 |
| `evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.svg` | generated golden | ~110 |

**Estimated total ≈ 640 changed lines, of which ~150 are generated golden
bytes**; hand-written, review-bearing code is ~490. This is at/near the
"Dispatch checklist" section's stated preference, "Prefer PRs below roughly
600 changed lines and split work that cannot be reviewed independently."
**Size lever if the lead wants a hard sub-600 diff:** drop the committed golden
SVG (−110) and prove SVG determinism with the render-twice byte-equality
assertion plus structural assertions instead. Take the lever or leave it, but
say which on dispatch.

`evals` is already on `[tool.pytest.ini_options] pythonpath` and `testpaths`
(`pyproject.toml:27-42`), so `evals/reporting/` is importable as `reporting.*`
(same convention as the existing `harness.*` and `graders.*`) and
`evals/tests/**` is already collected. **No scaffold-registration edits are
needed or permitted** — see Allowed/forbidden paths.

### Acceptance criteria

**AC1 — Markdown summary.**
`render_markdown(report: dict) -> str` emits GitHub-flavored Markdown with:

1. A **provenance banner** at the top carrying `mode`, `acceptance.accepted`,
   and the verbatim `provenance_note`. For `mode: "synthetic"` the banner must
   make it impossible to mistake the output for a live acceptance artifact
   (`SCHEMA.md:128-133`: "Synthetic reports are never acceptance-grade"; the
   committed report is *not* the T0112 acceptance artifact).
2. A **provenance block**: `label`, `generated_at`, `run.run_id`, `run.as_of`,
   `run.identity_namespace`, `cohort.path`, `cohort.sha256`,
   `cohort.issuer_count`, `pipeline.parser_version`,
   `pipeline.normalizer_version`, `pipeline.queue`, `pipeline.jobs_completed`.
3. An **acceptance block**: `accepted` plus every entry of `reasons`.
4. A **totals table** from `totals` (13 fields).
5. A **per-issuer table**, one row per entry of `issuers`, columns: ticker,
   cik, expected_documents, documents_ingested, documents_parsed,
   documents_quarantined, facts_total, facts_canonical, facts_duplicate,
   facts_restated, spans_total, spans_verified, span_hash_verification_rate.
6. A **quarantine table** from `totals.quarantine_reason_distribution`
   (currently `{UNKNOWN_CONTEXT: 3, UNKNOWN_FORMAT: 3}`); renders `none` when
   the object is empty.
7. A **jobs table** from `pipeline.jobs`: `discovery_expected`,
   `fetch_expected`, `terminal_counts`, `pending`, `backlog_after_run`, and
   the lengths of `missing_fetch_jobs` / `surplus_fetch_jobs` /
   `stale_fetch_jobs` / `failures`.

**AC2 — Row order is cohort order, never value order.** `issuers` is rendered
in the order it appears in the JSON (`SCHEMA.md:149`: "in cohort order"). No
sorting, no ranking, no "worst first". Same for `run.expected_issuers`.

**AC3 — Numeric fidelity.**
- `span_hash_verification_rate` is an exact 6-dp decimal **string**
  (`SCHEMA.md:185`). It is echoed **verbatim**. Never parsed to `float`, never
  re-rounded, never reformatted as a percentage, never passed through
  `Decimal` and back.
- `cik` is a zero-padded string (e.g. `"0001108524"`). It is echoed verbatim
  and wrapped in backticks so no downstream renderer can strip leading zeros
  or treat it as a number. Never `int()`-coerced.
- Any cell value containing `|` is escaped as `\|`; newlines in free text
  (e.g. `provenance_note`, acceptance `reasons`) are collapsed to spaces inside
  table cells. `provenance_note` in the banner is emitted as a blockquote, not
  a cell, so it survives intact.

**AC4 — The `"unavailable"` sentinel.** When `spans_total == 0` the rate is the
literal string `"unavailable"` — "an empty denominator is NEVER reported as
`1`" (`SCHEMA.md:185`). The renderer must:
- print the literal token `unavailable` (never `0.000000`, never `100%`, never
  `—`, never an empty cell);
- never let an `unavailable` issuer contribute to any derived figure — the
  renderer computes **no** derived rates of its own, it only echoes
  `totals.span_hash_verification_rate` as given;
- in the SVG, draw the issuer's bar from its integer document counts (which are
  always present) and mark it in the row label; a missing rate never becomes a
  zero-height or full-height bar.

  **The one committed report exercises none of this** — all 20 issuers have
  `spans_total > 0` and rate `"1.000000"`. Coverage therefore comes from an
  **in-memory** fixture dict built inside the test module. Do **not** write a
  fabricated report JSON into `evals/reports/**`: "never hand-edit a report:
  reports are generated artifacts, and fabricating real-issuer numbers is
  prohibited" (`SCHEMA.md:246-249`).

**AC5 — The `corpus-qa-failure/v1` sibling variant.** A failed run writes a
different schema to the **same** `<label>.json` path (`SCHEMA.md:61-73`). It has
**no** `issuers`, **no** `totals`, **no** `pipeline`; it has `run_failure`
(`failure_reason` plus `jobs_completed` and `jobs`, either of which may be
`null`) and `acceptance` fixed to `{"accepted": false, ...}`. The renderer must:
- dispatch on the `schema` field, never on the filename;
- render a **Markdown-only** failure summary with a `RUN FAILURE` banner,
  `failure_reason`, every acceptance reason, the shared provenance fields, and
  the jobs summary **only when non-`null`** (print `not accounted` otherwise);
- write **no SVG** — there is nothing to chart — and say so on stderr. An empty
  or all-zero chart that could read as "0 problems" is a defect, not a
  degradation;
- exit 0. Rendering a failure report is a successful render.

**AC6 — Schema gate, fail closed.** The renderer accepts only
`schema == "corpus-qa-report/v1"` with `schema_version == 1`, or
`schema == "corpus-qa-failure/v1"`. Anything else → one-line stderr message,
nothing written, **exit 2**, mirroring the harness's pre-work refusal
convention (`SCHEMA.md:51-58`). Same for an unreadable path or malformed JSON.
No raw traceback on any anticipated path.

The renderer does **not** reimplement `harness.corpus_qa.validate_report`; deep
structural/provenance validation stays owned by the harness. It also must not
*import* `harness.corpus_qa` at runtime — that module imports `psycopg`,
`fel_providers`, and `fel_workers` at module top
(`evals/harness/corpus_qa.py:107-125`), which would drag a database driver into
a file-only tool. A test-time drift guard imports the harness (fine under
pytest) and asserts the renderer's four constants equal
`harness.corpus_qa.REPORT_SCHEMA`, `REPORT_SCHEMA_VERSION`, `FAILURE_SCHEMA`,
and `RATE_UNAVAILABLE` (`corpus_qa.py:128,132,133,172`).

**AC7 — SVG chart, hand-written via `xml.etree.ElementTree`.**
A single-snapshot **horizontal stacked bar chart**, one row per issuer in cohort
order, segmented `documents_parsed` / `documents_ingested − documents_parsed −
documents_quarantined` / `documents_quarantined`, plus a totals row, a legend,
and a value axis.
- Root: `<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 W H"
  width="W" height="H">` with child `<title>` and `<desc>` for accessibility.
- **Integer coordinates only.** Every x/y/width/height is computed in `int`
  arithmetic so no float `repr` can vary. No `%`-of-container, no CSS.
- Axis maximum = `max((i["documents_ingested"] for i in issuers), default=1)`,
  floored at `1`, so that neither an all-zero report nor an empty `issuers`
  list can divide by zero or raise.
- No external font, no `@import`, no embedded raster, no external URL: generic
  `font-family="monospace"` only.
- Serialized as `'<?xml version="1.0" encoding="UTF-8"?>\n'` +
  `ET.indent(root, space="  ")` + `ET.tostring(root, encoding="unicode")` +
  `"\n"`, written with `encoding="utf-8", newline="\n"`.

**AC8 — Byte determinism.** Rendering the same input twice, on any machine, on
any day, produces byte-identical Markdown and SVG.
- **No wall clock.** `datetime.now()`, `time.time()`, `uuid4()`, `random`, and
  `os.urandom` must not appear. The only timestamp emitted is `generated_at`
  copied verbatim from the input.
- No `set` / `dict` iteration whose order depends on hashing: iterate
  `quarantine_reasons` and `terminal_counts` in `sorted()` key order (both are
  small string-keyed maps), and document that choice.
- No locale-sensitive formatting; no thousands separators derived from locale.
- `ET` attribute insertion order is preserved on Python 3.11 (`.python-version`
  = `3.11`) — verified: `ET.tostring` on an element built with attributes
  `z,a,m` emits `z="1" a="2" m="3"`.
- Tests assert byte-equality against each committed golden **and** assert
  `render(x) == render(x)` across two independent calls. If the size lever
  below is taken, only the Markdown golden is committed and the SVG is proved
  by the render-twice assertion alone; the Files-created table and the
  allowed-paths list drop the SVG golden accordingly.

**AC9 — n=1 is a hard design constraint, stated in code and README.** There is
exactly **one** committed report. There is **no time series**. The renderer
therefore:
- takes exactly **one** report path per invocation; there is no `--compare`, no
  glob, no directory scan, no multi-report aggregation;
- emits **no** trend line, delta, sparkline, "change since", or run-over-run
  arrow — a second data point does not exist and inventing one would be a
  fabricated finding;
- the chart's only comparison axis is **across issuers within the single
  snapshot**, which is exactly what one observation supports;
- the README states this explicitly and records that a multi-report view is
  deferred until ≥2 reports are committed (realistically the deferred live
  T0112 run, `SCHEMA.md:207-249`).

**AC10 — Stdlib-only, enforced by a test.** A unit test AST-scans
`evals/reporting/corpus_qa_render.py` for every top-level import and asserts
each root module is in `sys.stdlib_module_names`. The renderer's whole import
set is expected to be: `argparse`, `json`, `pathlib`, `sys`,
`xml.etree.ElementTree` (+ `typing`/`collections.abc` for annotations).

**AC11 — No database, no network.** The full new test module passes with
`TEST_DATABASE_URL` unset (`evals/tests/conftest.py` skips DB-backed suites
without it). Proven by the `env -u TEST_DATABASE_URL` run in evidence.

**AC12 — bandit clean without touching shared config.** `bandit -q -r … evals …
-c pyproject.toml` currently **fails** on `import xml.etree.ElementTree`:

```
[B405:blacklist] Using xml.etree.ElementTree to parse untrusted XML data …
Severity: Low   Confidence: High   →  bandit exit=1
```

I reproduced this against the repo's own `[tool.bandit]` config (bandit 1.9.4,
`pyproject.toml:45-46` sets only `exclude_dirs`, no `skips`, and CI has no
severity floor — `ci.yml:103`). Because this repo has **no** existing
`xml`/`ElementTree` import anywhere, this lands the first one and must be
handled. **Required remedy — inline pragma only:**

```python
# Build-only SVG emitter: this module never parses XML, so the XXE class
# B405 warns about is unreachable. Justification kept off the pragma line
# so bandit does not read the prose as test ids.
import xml.etree.ElementTree as ET  # nosec B405
```

Verified: this form takes bandit to `exit=0` with no warnings, and passes
`ruff check` and `black --check` under the repo config. Prose on the pragma
line itself makes bandit emit `WARNING Test in comment: … is not a test name`
noise — keep it on the preceding lines.

**Explicitly forbidden alternative:** adding `skips` to `[tool.bandit]` in
`pyproject.toml`. That is a shared-path edit outside the ADR-0008 dir-list
exception, and it would blind the whole repo to B405 forever.

**Escape hatch if the lead rejects the `nosec`:** emit the SVG by the same
deterministic token-substitution used in `evals/harness/synthetic_sec.py:147-169`
(`render_filing`), dropping `ElementTree` entirely. Taking the hatch amends AC7
(its `ET.indent` / `ET.tostring` serialization steps no longer apply) and AC10
(`xml.etree.ElementTree` leaves the expected import set, so the AST-scan test
asserts the smaller set); every other AC is unchanged.
Ask on the issue before switching; do not decide unilaterally.

### Why stdlib, not a charting dependency

Adding any dependency is **explicitly excluded** from every standing shared-path
exception: ADR-0008 (`docs/decisions/ADR-0008-python-package-scaffold-edits.md:40-50`)
puts "Dependency additions of any kind — `requirements-dev.txt` and the
`pyproject.toml` dependency tables" outside the mechanical-scaffolding grant,
because "adding a dependency is a supply-chain and behavior change, not
mechanical scaffolding". Constitution **Principle V** (Simplicity and Provider
Isolation) requires "the smallest architecture that satisfies measured
requirements" and makes "any stack addition or substitution … require benchmark
evidence and an approved ADR, per the change rule in ADR-0002"; that change rule
(`docs/decisions/ADR-0002-mvp-stack.md:47`) admits a stack change only "with
benchmark evidence that the current default fails a requirement" — and a
20-row table plus one bar chart is not evidence that the stdlib fails. (ECharts
is the approved charting library, but it is the *frontend* one, for
`apps/web/**`; it is not reachable from a Python CLI.) The repo already has two
working stdlib precedents for exactly this shape of problem:
`workers/src/fel_workers/ingestion/parser.py:1-3` — "Stdlib-only
(``html.parser``); no new root dependency" — and
`evals/harness/synthetic_sec.py:147-169`, which already does deterministic
token-substitution HTML template rendering. `json`, `xml.etree.ElementTree`,
and `str.join` cover this entirely.

---

## Dependencies and frozen contract versions

*(form field `dependencies`, `type: textarea`, required)*

### Base

- Base branch: `main`
- Base SHA: `eed2140` (current `origin/main` tip; `STATUS.md` was last updated
  at `ad1717b` — confirm the tip at dispatch and pin it in the worker prompt).
- Working branch: `agent/evals-report-render` (one branch, one worktree).

### Package dependencies

| Package | Issue | Status | Why |
| --- | --- | --- | --- |
| `M1-CORPUS-QA` | #56 | merged @ `1a96228` | Owns `evals/harness/corpus_qa.py`, the `corpus-qa-report/v1` schema, `SCHEMA.md`, and the single committed report this package reads. |

No other edge. This package reads a committed file and writes text; it touches
no API, no database, no migration, no queue, no provider.

### Frozen inputs (read-only; changing any is out of scope)

| Input | Version / pin |
| --- | --- |
| Report schema | `corpus-qa-report/v1`, `schema_version` **1** (`corpus_qa.py:128,133`) |
| Failure sibling schema | `corpus-qa-failure/v1` (`corpus_qa.py:132`) |
| Rate sentinel | `RATE_UNAVAILABLE = "unavailable"` (`corpus_qa.py:172`) |
| Schema documentation | `evals/reports/corpus-qa/SCHEMA.md` |
| Sole input artifact | `evals/reports/corpus-qa/2026-07-14-synthetic-cohort.json`, 13,190 bytes, sha256 `4f0458e8df3566649d80851e29665fb51f0e979cc15613f23a606ccf6a7bdd7a` |
| Cohort pinned by that report | `evals/datasets/issuer-cohort.json`, sha256 `3fda084f60f4fd00225d36e0e6233ac03d0f2ff4420cad1b9d2ef95cf72e4b4c`, `as_of` `2026-07-13`, 20 issuers |
| Pipeline versions recorded in it | parser `fel-parser/1.0.0`, normalizer `fel-xbrl/1.0.0` |
| Python | 3.11 (`.python-version`) |

OpenAPI / DB contracts (v0.4.0, migrations `0001`–`0005`) are **not** inputs and
must not be touched: this package has no API or database surface.

### Path-overlap serialization (README's "Dispatch checklist" section)

`evals/**` is **not** a shared path, but it is claimed by several packages, and
overlap is "resolved by time, not ownership" (`workstreams.yaml:87-90`). The
README's "Dispatch checklist" section states the same governing rule: "A
package is ready only when: ... no active package overlaps its allowed
paths ...". Other
`evals/**` claimants: M1-CORPUS-QA (#56, merged), READER-CROSS-STACK (#96,
merged), M2-CLAIMS-VERIFICATION (#58, merged), M3-CONFIDENCE-GATE (#62,
pending), M5-BACKTEST (#67, pending), M5-AUDIT-RELEASE (#68, pending),
READER-PROD-SMOKE (#108, **blocked**, also holds `evals/**`).

At the time of writing `STATUS.md` reports **Active: None**, and the only
`ready` package — M3-EXTRACTION-CORE (#60) — holds
`packages/ontology/**`, `packages/providers/**`,
`workers/src/fel_workers/extraction/**`, `workers/src/fel_workers/consumer.py`,
`workers/src/fel_workers/__main__.py`, `workers/tests/**`. **No overlap with
`evals/**`**, so this package can run concurrently with #60. Do **not** dispatch
it concurrently with #62, #67, #68, or an unblocked #108.

### Blocking prerequisite (integration lead, not the agent)

`docs/handoff/workstreams.yaml` and `docs/handoff/STATUS.md` are shared paths.
The lead must register `EVALS-REPORT-RENDER` (entry above) and mark it `ready`
before dispatch. The agent must not edit either file.

---

## Allowed and forbidden paths

*(form field `paths`, `type: textarea`, required)*

### Allowed (write)

```
evals/reporting/**          # new; the whole implementation
evals/tests/**              # new test module + golden fixtures
```

Concretely, the only files this PR may create or modify:

```
evals/reporting/__init__.py
evals/reporting/corpus_qa_render.py
evals/reporting/README.md
evals/tests/test_corpus_qa_render.py
evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.md
evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.svg
```

### Read-only (must not be modified)

```
evals/reports/corpus-qa/**       # the input artifact and its SCHEMA.md
evals/harness/**                 # corpus_qa.py, synthetic_sec.py (test-time import only)
evals/datasets/**
```

### Forbidden — shared paths (`AGENTS.md:27-41`, `workstreams.yaml:6-33`)

```
.github/**                       # incl. workflows/ci.yml — NO CI wiring
.specify/**
.agents/**
specs/**                         # incl. tasks.md — agents never check Spec Kit boxes
packages/contracts/**
db/migrations/**
docs/decisions/**
docs/handoff/workstreams.yaml
docs/handoff/STATUS.md
package.json, pnpm-lock.yaml, pnpm-workspace.yaml, tsconfig.json,
tsconfig.base.json, vitest.config.ts, eslint.config.mjs, .prettierrc.json,
.prettierignore, .editorconfig, .gitignore, .node-version, .python-version,
pyproject.toml, requirements-dev.txt, Makefile
```

### Forbidden — other packages' code

```
apps/**, workers/**, packages/**, infra/**, db/**, docs/**, scripts/**
```

This package writes no documentation outside `evals/reporting/README.md`.

### Explicitly NOT invoking the ADR-0008 exception

ADR-0008 lets a **new first-party package under `packages/**`** register its
directory in `pyproject.toml` / `Makefile` / `ci.yml` dir-lists. **This package
does not qualify and does not need it:** `evals` is already in `[tool.ruff]
src`, `[tool.mypy] mypy_path`, `[tool.pytest.ini_options] pythonpath`, and
`testpaths` (`pyproject.toml:4-42`), and already in the `black`/`ruff`/`bandit`
lists in `Makefile:21-46` and `ci.yml:99-104`. **Any diff hunk in those three
files is a process violation on this PR.**

**Known, accepted gap — declare it in the PR, do not "fix" it.** The CI `mypy`
line is `mypy apps/api/app workers/src evals/graders packages/providers/… …`
(`ci.yml:101`, `Makefile:33`) — it names `evals/graders`, **not** `evals/` — so
`evals/reporting/**` will **not** be typechecked by CI, exactly as
`evals/harness/**` is not today. The module must still be fully type-annotated
and must pass `mypy` (strict, per `pyproject.toml:20-22`) when pointed at it
manually; that run is required evidence below. Extending the dir-list is a
shared-path change for the integration lead, outside this package. Flag it in
the PR as a follow-up, do not do it.

---

## Required checks and evidence

*(form field `tests`, `type: textarea`, required)*

### Baseline first (before editing) — record output in the PR

```bash
make install            # once per worktree: pnpm install + .venv + requirements-dev.txt
make ci                 # format-check → lint → typecheck → test → security
```

`make ci` = `format-check lint typecheck test security` (`Makefile:48`) and uses
`.venv/bin` (`Makefile:2`). Note `security` runs `pip-audit` and
`node scripts/audit-bulk.mjs`, which need network; if the sandbox blocks them,
say so and run the Python subset below instead of claiming a green gate.

### Full gate again after the change

```bash
make ci
```

### Python job, exactly as CI runs it (`.github/workflows/ci.yml:99-104`)

```bash
.venv/bin/black --check apps workers evals packages/providers packages/retrieval packages/retrieval-evals
.venv/bin/ruff check apps workers evals packages/providers packages/retrieval packages/retrieval-evals
.venv/bin/mypy apps/api/app workers/src evals/graders packages/providers/fel_providers packages/retrieval/fel_retrieval packages/retrieval-evals/fel_retrieval_evals
.venv/bin/pytest
.venv/bin/bandit -q -r apps workers evals packages/providers packages/retrieval packages/retrieval-evals -c pyproject.toml
.venv/bin/pip-audit -r requirements-dev.txt
```

`bandit` must exit **0** — this is the B405 check from AC12, and it is the one
gate most likely to break. Paste its exit code.

### Targeted tests

```bash
.venv/bin/pytest evals/tests/test_corpus_qa_render.py -v
```

No `PYTHONPATH` needed: `[tool.pytest.ini_options] pythonpath` already lists
`evals` (`pyproject.toml:27-34`).

### DB-free proof (AC11)

```bash
env -u TEST_DATABASE_URL .venv/bin/pytest evals/tests/test_corpus_qa_render.py -v
```

Every test in the new module must **run**, not skip.

### Extra mypy, since CI's dir-list does not reach this module

```bash
.venv/bin/mypy evals/reporting
```

Must be clean under the repo's `strict = true` (`pyproject.toml:20-22`).

### CLI smoke — stdlib-only import path

```bash
PYTHONPATH=evals .venv/bin/python -m reporting.corpus_qa_render \
  evals/reports/corpus-qa/2026-07-14-synthetic-cohort.json \
  --out-dir /tmp/fel-render-a
```

Note `PYTHONPATH=evals` alone — contrast with the harness recipe
(`SCHEMA.md:198`), which needs `evals:workers/src:packages/providers:apps/api`.
That difference **is** the stdlib-only proof: paste it.

### Byte-determinism proof (AC8)

```bash
PYTHONPATH=evals .venv/bin/python -m reporting.corpus_qa_render \
  evals/reports/corpus-qa/2026-07-14-synthetic-cohort.json --out-dir /tmp/fel-render-b
diff -r /tmp/fel-render-a /tmp/fel-render-b && echo "BYTE-IDENTICAL"
diff /tmp/fel-render-a/2026-07-14-synthetic-cohort.md \
     evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.md && echo "GOLDEN MD OK"
diff /tmp/fel-render-a/2026-07-14-synthetic-cohort.svg \
     evals/tests/golden/corpus-qa/2026-07-14-synthetic-cohort.svg && echo "GOLDEN SVG OK"
```

### Fail-closed proof (AC6)

```bash
echo '{"schema":"nope","schema_version":9}' > /tmp/bad.json
PYTHONPATH=evals .venv/bin/python -m reporting.corpus_qa_render /tmp/bad.json --out-dir /tmp/out
echo "exit=$?"    # expect 2, one-line stderr message, nothing written, no traceback
```

### Required evidence in the PR (`workstreams.yaml:64`)

- **tests** — the commands above with their exit codes.
- **telemetry-if-applicable** — N/A; a file-in/file-out CLI emits none. State it.
- **documentation** — `evals/reporting/README.md` (usage, determinism contract,
  the n=1 constraint, the `unavailable` and failure-variant behavior, the
  `# nosec B405` justification, and the "not in CI's mypy dir-list" note).
- **acceptance-notes** — AC1–AC12 each ticked with the command or test name
  that proves it; the rendered Markdown pasted inline; the rendered SVG
  attached as an image so a reviewer can look at the chart.
- **Explicitly declare** in the PR Scope: zero dependency changes, zero
  shared-path hunks, and the known mypy dir-list gap.

### Verified environment facts (so the agent does not rediscover them)

- Python 3.11.15; `ET.tostring` preserves attribute insertion order (no
  alphabetical re-sort since 3.8) — determinism holds.
- `bandit` 1.9.4 + this repo's config flags `import xml.etree.ElementTree` as
  **B405, exit 1**; `# nosec B405` with the justification on preceding lines
  returns exit 0 with no warning noise.
- `grep -rn "GITHUB_STEP_SUMMARY"` → **0** hits repo-wide.
- `grep -rn "import xml|from xml|ElementTree"` over `*.py` → **0** hits. This
  PR introduces the repo's first XML import.
- All 20 issuers in the committed report have `spans_total > 0` and rate
  `"1.000000"`; the `"unavailable"` path has **no** committed coverage and must
  be covered by an in-memory fixture.

---

## Credentials needed?

*(form field `credentials`, `type: dropdown`, required — pick one of
`"No — use mocks"` / `"Yes — integration lead must provision"`)*

```
No — use mocks
```

Nothing to provision. The renderer reads one committed JSON file and writes
text: no database, no network, no SEC egress, no `FEL_SEC_USER_AGENT`, no
provider key. Per AC11 the whole test module runs with `TEST_DATABASE_URL`
unset. `docs/handoff/CREDENTIALS.md` needs no new row.

---

## Agent contract

*(form field `contract`, `type: checkboxes`, required)*

- [x] I will use one branch/worktree, stay within allowed paths, push
      checkpoints, and never include secrets.

---

## Out of scope (explicit — do not do these)

1. **No CI wiring of any kind.** No `$GITHUB_STEP_SUMMARY` write, no new job,
   step, artifact upload, or workflow trigger. `.github/**` is a shared path
   (`AGENTS.md:31`), and ADR-0008 covers only "the `python` job's dir-list
   registration" — "`.github/**` edits beyond [that] … remain shared and require
   separate authorization" (`ADR-0008:54-57`). Publishing the rendered summary
   in CI is a good idea and a **separate**, lead-owned `contract-change` issue.
2. **No new dependency**, direct or transitive, dev or runtime. No edit to
   `requirements-dev.txt` or to `[project] dependencies` /
   `[project.optional-dependencies]` in `pyproject.toml`. Excluded from every
   standing exception by `ADR-0008:40-50`. No `tabulate`, `rich`, `jinja2`,
   `pandas`, `matplotlib`, `plotly`, `svgwrite`, `defusedxml`.
3. **No change to the report schema.** `corpus-qa-report/v1`,
   `corpus-qa-failure/v1`, `schema_version`, field names, the `"unavailable"`
   sentinel, the 6-dp decimal-string rate format, and the normative sections of
   `evals/reports/corpus-qa/SCHEMA.md` are all frozen inputs. No edit to
   `evals/harness/corpus_qa.py`.
4. **No new or regenerated report.** Do not run the harness, do not commit a
   new `evals/reports/**` JSON, do not hand-edit the existing one, do not
   fabricate issuer numbers (`SCHEMA.md:246-249`). Test fixtures stay in-memory
   or under `evals/tests/`.
5. **No shared-config dir-list edits.** No hunk in `pyproject.toml`, `Makefile`,
   or `.github/workflows/ci.yml` — including the tempting `[tool.bandit] skips`
   and the `mypy` dir-list. Use the inline `# nosec B405` (AC12) and declare the
   mypy gap.
6. **No time-series, comparison, or trend feature.** n=1. See AC9.
7. **No other report family.** The `Decimal` gate metrics in
   `packages/retrieval-evals/fel_retrieval_evals/metrics.py`
   (`GateReport.to_dict()`, currently surfaced only inside pytest assertions and
   never written to a file) are **not** in scope: `packages/retrieval-evals/**`
   is outside `allowed_paths` and belongs to M2-CLAIMS-VERIFICATION (#58). A
   `GateReport` renderer is the natural follow-up package — file it, don't do it.
8. **No HTML, PDF, PNG, or interactive output.** Markdown + SVG only. No
   ECharts: that is the approved **frontend** library for `apps/web/**`
   (constitution, Approved Technical Constraints), not reachable from a Python
   CLI.
9. **No Spec Kit bookkeeping.** Do not add `T0113` (or any ID) to
   `specs/001-financial-evidence-lab/tasks.md`, do not check a box, do not edit
   `workstreams.yaml` or `STATUS.md` (`AGENTS.md:24`, and README's "Source of
   truth" section: "Only the integration lead changes bundle status to
   `merged`, checks tasks, changes dependencies, or updates shared
   contracts.").
10. **No refactor of `evals/harness/**` or `evals/graders/**`.** Read them,
    import `harness.corpus_qa` only inside the test module's drift guard, change
    nothing.
