"""Issue #151: byte-deterministic renderer for one committed corpus-QA report.

Reads exactly ONE ``corpus-qa-report/v1`` JSON artifact (or its
``corpus-qa-failure/v1`` sibling) from
``evals/reports/corpus-qa/`` and writes a Markdown summary plus a
hand-written SVG chart. Input schema: ``evals/reports/corpus-qa/SCHEMA.md``.

Stdlib-only by contract: ``argparse``, ``json``, ``pathlib``, ``sys`` and
``xml.etree.ElementTree`` are the whole import set (plus typing helpers).
No database, no network, no dependency. In particular this module does NOT
import ``harness.corpus_qa``: that module pulls in ``psycopg``,
``fel_providers`` and ``fel_workers`` at import time, which would drag a
database driver into a file-in/file-out tool. The four schema constants
below are therefore duplicated, and a test-time drift guard
(``evals/tests/test_corpus_qa_render.py``) asserts they still equal the
harness's.

DETERMINISM IS THE PRODUCT. Rendering the same input twice, on any machine,
on any day, produces byte-identical output: no wall clock (``datetime``,
``time``, ``uuid``, ``random`` and ``os`` are not imported, and the only
timestamp emitted is ``generated_at`` copied verbatim from the input), no
hash-ordered iteration, no float anywhere in the output, and integer-only
SVG coordinates. ``evals/reporting/README.md`` states the full contract and
``evals/tests/golden/corpus-qa/`` pins the exact expected bytes.

n=1 IS A HARD DESIGN CONSTRAINT. Exactly one report is committed, so there
is no time series: this tool takes one report per invocation and emits no
trend, delta, sparkline or run-over-run comparison. The chart's only
comparison axis is across issuers within the single snapshot.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Build-only SVG emitter: this module constructs an element tree and
# serializes it. It never parses XML, so the XXE/quadratic-blowup class
# that bandit B405 warns about is unreachable here. Justification kept off
# the pragma line so bandit does not read the prose as test ids.
import xml.etree.ElementTree as ET  # nosec B405
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Frozen inputs owned by M1-CORPUS-QA (evals/harness/corpus_qa.py). Kept in
# sync by the drift guard in evals/tests/test_corpus_qa_render.py.
REPORT_SCHEMA = "corpus-qa-report/v1"
REPORT_SCHEMA_VERSION = 1
FAILURE_SCHEMA = "corpus-qa-failure/v1"
RATE_UNAVAILABLE = "unavailable"

#: Per-issuer table columns, in render order (SCHEMA.md "Per-issuer metrics").
ISSUER_COLUMNS: tuple[str, ...] = (
    "ticker",
    "cik",
    "expected_documents",
    "documents_ingested",
    "documents_parsed",
    "documents_quarantined",
    "facts_total",
    "facts_canonical",
    "facts_duplicate",
    "facts_restated",
    "spans_total",
    "spans_verified",
    "span_hash_verification_rate",
)

#: ``totals`` scalar fields, in render order. The thirteenth field,
#: ``quarantine_reason_distribution``, gets its own table (see AC1.6).
_TOTALS_FIELDS: tuple[str, ...] = (
    "expected_documents",
    "documents_ingested",
    "documents_parsed",
    "documents_quarantined",
    "document_versions_parsed",
    "facts_total",
    "facts_canonical",
    "facts_duplicate",
    "facts_restated",
    "spans_total",
    "spans_verified",
    "span_hash_verification_rate",
)

#: ``pipeline.jobs`` scalar fields rendered as-is.
_JOBS_SCALARS: tuple[str, ...] = ("discovery_expected", "fetch_expected", "pending")

#: ``pipeline.jobs`` array fields rendered as lengths (the arrays themselves
#: are failure detail, not summary).
_JOBS_ARRAYS: tuple[str, ...] = (
    "missing_fetch_jobs",
    "surplus_fetch_jobs",
    "stale_fetch_jobs",
    "failures",
)


class RenderError(Exception):
    """Anticipated, operator-facing failure. Reported as one stderr line
    and exit 2 -- never as a traceback."""


# --------------------------------------------------------------------------
# scalar formatting
# --------------------------------------------------------------------------


def _text(value: object) -> str:
    """Deterministic string form of a JSON scalar.

    ``bool`` is checked before ``int`` (``True`` is an ``int`` in Python).
    A ``float`` is not expected anywhere in this schema -- every count is an
    ``int`` and the one rate is a decimal STRING -- so it is given a fixed
    six-place format rather than a platform-visible ``repr``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return f"{value:.6f}"
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _cell(value: object) -> str:
    """Table-cell form: pipes escaped, line breaks and tabs collapsed to
    spaces so a multi-line free-text value cannot break the table."""
    text = _text(value)
    for char in ("\r\n", "\r", "\n", "\t"):
        text = text.replace(char, " ")
    return text.replace("|", r"\|")


def _code(value: object) -> str:
    """Table-cell form wrapped in a backtick fence wide enough to survive a
    value that itself contains backticks."""
    text = _cell(value)
    if not text:
        return "``"
    longest = 0
    run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _value(value: object) -> str:
    """Table-cell form for a report field.

    A STRING value is always code-fenced. That is what keeps ``cik``
    zero-padding (``"0001108524"``) and the six-place
    ``span_hash_verification_rate`` (``"1.000000"``) intact: no downstream
    Markdown renderer, spreadsheet paste or diff viewer can strip a leading
    zero, trim a trailing zero, or coerce the token to a number. A numeric
    value is emitted bare so it still reads as a count.
    """
    return _code(value) if isinstance(value, str) else _cell(value)


def _as_mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RenderError(f"{where}: expected an object, got {type(value).__name__}")
    return value


def _as_sequence(value: object, where: str) -> Sequence[Any]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise RenderError(f"{where}: expected an array, got {type(value).__name__}")
    return value


def _as_int(value: object, where: str) -> int:
    """Strict integer read for values that drive chart geometry. Rejects
    ``bool`` and ``float`` so no non-integer can reach a coordinate."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RenderError(f"{where}: expected an integer, got {type(value).__name__}")
    return value


def _dig(report: Mapping[str, Any], *path: str) -> Any:
    """Read a dotted path, returning ``None`` for any missing level.

    Deliberately forgiving: deep structural validation belongs to
    ``harness.corpus_qa.validate_report``, not here. A field this renderer
    cannot find renders as ``null`` rather than crashing.
    """
    node: Any = report
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


# --------------------------------------------------------------------------
# markdown primitives
# --------------------------------------------------------------------------


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _blockquote(text: str) -> list[str]:
    """Quote free text without altering it: each input line is prefixed, so
    a multi-line ``provenance_note`` survives intact instead of being
    collapsed into a table cell."""
    return [f"> {line}" if line else ">" for line in text.split("\n")]


def _field_rows(report: Mapping[str, Any], paths: Sequence[tuple[str, ...]]) -> list[list[str]]:
    return [[_code(".".join(path)), _value(_dig(report, *path))] for path in paths]


# --------------------------------------------------------------------------
# markdown rendering
# --------------------------------------------------------------------------

_REPORT_PROVENANCE: tuple[tuple[str, ...], ...] = (
    ("label",),
    ("generated_at",),
    ("run", "run_id"),
    ("run", "as_of"),
    ("run", "identity_namespace"),
    ("cohort", "path"),
    ("cohort", "sha256"),
    ("cohort", "issuer_count"),
    ("pipeline", "parser_version"),
    ("pipeline", "normalizer_version"),
    ("pipeline", "queue"),
    ("pipeline", "jobs_completed"),
)

_FAILURE_PROVENANCE: tuple[tuple[str, ...], ...] = (
    ("label",),
    ("generated_at",),
    ("run", "run_id"),
    ("run", "as_of"),
    ("run", "identity_namespace"),
    ("cohort", "path"),
    ("cohort", "sha256"),
    ("cohort", "issuer_count"),
)


def _accepted(report: Mapping[str, Any]) -> bool:
    return _dig(report, "acceptance", "accepted") is True


def _banner(report: Mapping[str, Any], *, failure: bool) -> list[str]:
    """Provenance banner. For a synthetic report it must be impossible to
    mistake the output for a live acceptance artifact: synthetic reports are
    never acceptance-grade (SCHEMA.md, "Run success vs acceptance")."""
    mode = _text(report.get("mode"))
    accepted = "yes" if _accepted(report) else "no"
    if failure:
        headline = (
            "RUN FAILURE. The run failed after work started; no corpus metrics were produced."
        )
    elif mode == "synthetic":
        headline = (
            "SYNTHETIC RUN. NOT AN ACCEPTANCE ARTIFACT: synthetic reports are never "
            "acceptance-grade, and no metric below describes any real company's filings."
        )
    elif mode == "live":
        headline = "LIVE RUN." if _accepted(report) else "LIVE RUN. NOT ACCEPTED."
    else:
        headline = f"UNRECOGNIZED MODE {mode!r}. Treat every figure below as unattributed."
    lines = [
        f"> **{headline}**",
        ">",
        f"> Mode: {_code(mode)}. Accepted: **{accepted}**.",
        ">",
    ]
    lines.extend(_blockquote(_text(report.get("provenance_note"))))
    return lines


def _acceptance_section(report: Mapping[str, Any]) -> list[str]:
    lines = ["## Acceptance", "", f"Accepted: **{'yes' if _accepted(report) else 'no'}**", ""]
    reasons = _dig(report, "acceptance", "reasons")
    if isinstance(reasons, Sequence) and not isinstance(reasons, str) and reasons:
        # Input order: reasons are emitted by the harness in the order it
        # discovered them; re-ordering them would misreport the run.
        lines.extend(f"- {_cell(reason)}" for reason in reasons)
    else:
        lines.append("- none recorded")
    return lines


def _quarantine_section(distribution: object) -> list[str]:
    lines = ["## Quarantine reasons", ""]
    if not isinstance(distribution, Mapping) or not distribution:
        lines.append("none")
        return lines
    # sorted(): reason codes are an unordered string-keyed map, so key order
    # is pinned here rather than inherited from JSON/dict insertion order.
    rows = [[_code(reason), _value(distribution[reason])] for reason in sorted(distribution)]
    lines.extend(_table(("Reason", "Count"), rows))
    return lines


def _jobs_rows(jobs: Mapping[str, Any]) -> list[list[str]]:
    rows = [[_code(field), _value(jobs.get(field))] for field in _JOBS_SCALARS]
    terminal = jobs.get("terminal_counts")
    if isinstance(terminal, Mapping) and terminal:
        # sorted(): status -> count is an unordered string-keyed map.
        summary = ", ".join(f"{status}={_text(terminal[status])}" for status in sorted(terminal))
    else:
        summary = "none"
    rows.append([_code("terminal_counts"), _value(summary)])
    rows.append([_code("backlog_after_run"), _value(jobs.get("backlog_after_run"))])
    for field in _JOBS_ARRAYS:
        value = jobs.get(field)
        count = len(value) if isinstance(value, Sequence) and not isinstance(value, str) else 0
        rows.append([_code(f"{field} (count)"), _value(count)])
    return rows


def _render_report_markdown(report: Mapping[str, Any]) -> str:
    label = _text(report.get("label"))
    lines = [f"# Corpus QA report: {_code(label)}", ""]
    lines.extend(_banner(report, failure=False))
    lines.append("")

    lines.extend(["## Provenance", ""])
    lines.extend(_table(("Field", "Value"), _field_rows(report, _REPORT_PROVENANCE)))
    expected = _dig(report, "run", "expected_issuers")
    if isinstance(expected, Sequence) and not isinstance(expected, str):
        # Cohort order, echoed as given (AC2).
        joined = ", ".join(_text(ticker) for ticker in expected)
        lines.append(f"| {_code('run.expected_issuers')} | {_code(joined)} |")
    lines.append("")

    lines.extend(_acceptance_section(report))
    lines.append("")

    totals = _as_mapping(report.get("totals"), "totals")
    lines.extend(["## Totals", ""])
    totals_rows = [[_code(field), _value(totals.get(field))] for field in _TOTALS_FIELDS]
    lines.extend(_table(("Metric", "Value"), totals_rows))
    lines.append("")

    issuers = _as_sequence(report.get("issuers"), "issuers")
    lines.extend(
        ["## Per-issuer metrics", "", "Cohort order, exactly as recorded. Not ranked.", ""]
    )
    issuer_rows = []
    for index, raw in enumerate(issuers):
        issuer = _as_mapping(raw, f"issuers[{index}]")
        issuer_rows.append([_value(issuer.get(column)) for column in ISSUER_COLUMNS])
    lines.extend(_table(ISSUER_COLUMNS, issuer_rows))
    lines.append("")

    lines.extend(_quarantine_section(totals.get("quarantine_reason_distribution")))
    lines.append("")

    lines.extend(["## Jobs", ""])
    jobs = _dig(report, "pipeline", "jobs")
    if isinstance(jobs, Mapping):
        lines.extend(_table(("Field", "Value"), _jobs_rows(jobs)))
    else:
        lines.append("not accounted")
    return "\n".join(lines) + "\n"


def _render_failure_markdown(report: Mapping[str, Any]) -> str:
    label = _text(report.get("label"))
    lines = [f"# Corpus QA run failure: {_code(label)}", ""]
    lines.extend(_banner(report, failure=True))
    lines.append("")

    lines.extend(["## Failure", ""])
    lines.append(
        f"- {_code('failure_reason')}: {_cell(_dig(report, 'run_failure', 'failure_reason'))}"
    )
    lines.append("")

    lines.extend(_acceptance_section(report))
    lines.append("")

    lines.extend(["## Provenance", ""])
    lines.extend(_table(("Field", "Value"), _field_rows(report, _FAILURE_PROVENANCE)))
    lines.append("")

    lines.extend(["## Jobs", ""])
    completed = _dig(report, "run_failure", "jobs_completed")
    lines.append(
        f"- {_code('jobs_completed')}: "
        + ("not accounted" if completed is None else _cell(completed))
    )
    lines.append("")
    jobs = _dig(report, "run_failure", "jobs")
    if isinstance(jobs, Mapping):
        lines.extend(_table(("Field", "Value"), _jobs_rows(jobs)))
    else:
        # Either-or-null by schema: an absent jobs summary is reported as
        # unknown, never as a table of zeroes that could read as "no problems".
        lines.append(f"- {_code('jobs')}: not accounted")
    return "\n".join(lines) + "\n"


def is_failure_report(report: Mapping[str, Any]) -> bool:
    """Dispatch on the ``schema`` field, never on the filename: a failed run
    writes the failure schema to the same ``<label>.json`` path."""
    return report.get("schema") == FAILURE_SCHEMA


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render one validated report to GitHub-flavored Markdown."""
    if is_failure_report(report):
        return _render_failure_markdown(report)
    return _render_report_markdown(report)


# --------------------------------------------------------------------------
# SVG rendering -- integer coordinates only
# --------------------------------------------------------------------------

_SVG_NS = "http://www.w3.org/2000/svg"
_MARGIN_LEFT = 128
_MARGIN_RIGHT = 64
_MARGIN_TOP = 72
_PLOT_WIDTH = 480
_ROW_HEIGHT = 20
_BAR_HEIGHT = 12
#: Vertical band below the issuer rows: tick labels, axis caption, separator,
#: the totals row, its caption, and the ``unavailable`` footnote. Fixed, so
#: the canvas height is a pure function of the issuer count.
_FOOTER_HEIGHT = 96
_TICKS = 4
_FONT = "monospace"

_COLOR_PARSED = "#2f6f4f"
_COLOR_UNPARSED = "#9aa3b0"
_COLOR_QUARANTINED = "#a33a3a"
_COLOR_TEXT = "#1b1f24"
_COLOR_GRID = "#d5d9e0"

_LEGEND: tuple[tuple[str, str], ...] = (
    (_COLOR_PARSED, "documents_parsed"),
    (_COLOR_UNPARSED, "ingested not parsed"),
    (_COLOR_QUARANTINED, "documents_quarantined"),
)


class _Row:
    """One chart row, already reduced to integers."""

    __slots__ = ("label", "parsed", "unparsed", "quarantined", "rate_unavailable")

    def __init__(self, label: str, source: Mapping[str, Any], where: str) -> None:
        ingested = _as_int(source.get("documents_ingested"), f"{where}.documents_ingested")
        parsed = _as_int(source.get("documents_parsed"), f"{where}.documents_parsed")
        quarantined = _as_int(source.get("documents_quarantined"), f"{where}.documents_quarantined")
        self.label = label
        self.parsed = parsed
        self.quarantined = quarantined
        # Clamped: the three counts are measured independently, so a report
        # where parsed + quarantined exceeds ingested must not produce a
        # negative segment width.
        self.unparsed = max(0, ingested - parsed - quarantined)
        # AC4: a missing rate is a MISSING measurement. It is marked on the
        # label and never drawn -- the bar comes from document counts, which
        # are always present, so it can be neither zero- nor full-height.
        self.rate_unavailable = source.get("span_hash_verification_rate") == RATE_UNAVAILABLE

    @property
    def total(self) -> int:
        return self.parsed + self.unparsed + self.quarantined

    @property
    def text(self) -> str:
        return f"{self.label} *" if self.rate_unavailable else self.label


def _chart_rows(report: Mapping[str, Any]) -> list[_Row]:
    """Issuer rows, in cohort order. The totals row is built separately: it
    lives on its own scale (see :func:`render_svg`)."""
    issuers = _as_sequence(report.get("issuers"), "issuers")
    rows = []
    # enumerate over the input sequence: cohort order, never value order.
    for index, raw in enumerate(issuers):
        where = f"issuers[{index}]"
        issuer = _as_mapping(raw, where)
        rows.append(_Row(_text(issuer.get("ticker")), issuer, where))
    return rows


def _axis_maximum(report: Mapping[str, Any]) -> int:
    """Largest ``documents_ingested`` across issuers, floored at 1 so that
    neither an empty ``issuers`` list nor an all-zero report can divide by
    zero."""
    issuers = _as_sequence(report.get("issuers"), "issuers")
    values = [
        _as_int(
            _as_mapping(issuer, f"issuers[{index}]").get("documents_ingested"),
            f"issuers[{index}].documents_ingested",
        )
        for index, issuer in enumerate(issuers)
    ]
    return max(max(values, default=1), 1)


def _px(value: int, axis_max: int) -> int:
    """Value -> pixels, in integer arithmetic (floor division). No float can
    reach a coordinate, so no float ``repr`` can vary between interpreters."""
    return (value * _PLOT_WIDTH) // axis_max


def _draw_bar(parent: ET.Element, row: _Row, y: int, scale: int) -> None:
    """Draw one stacked bar, left to right: parsed, ingested-not-parsed,
    quarantined. Segment widths come from the row's integer document counts
    only -- never from ``span_hash_verification_rate``, which may be the
    ``unavailable`` sentinel."""
    _text_node(parent, _MARGIN_LEFT - 8, y + 10, row.text, anchor="end")
    # The axis is pinned to max(documents_ingested) (AC7), but the segments are
    # driven by parsed + unparsed + quarantined. Those agree only for a
    # self-consistent record: `parsed + quarantined > ingested` -- which
    # `check_schema` accepts -- otherwise runs the bar past the plot and off
    # the canvas entirely, overpainting the count label beyond it. Clamped so a
    # malformed record cannot draw outside its own chart; the absolute count
    # printed at the end of every row remains the source of truth.
    limit = _MARGIN_LEFT + _PLOT_WIDTH
    x = _MARGIN_LEFT
    x = _segment(
        parent, x, y, _px(row.parsed, scale), _COLOR_PARSED, f"parsed {row.parsed}", limit=limit
    )
    x = _segment(
        parent,
        x,
        y,
        _px(row.unparsed, scale),
        _COLOR_UNPARSED,
        f"unparsed {row.unparsed}",
        limit=limit,
    )
    _segment(
        parent,
        x,
        y,
        _px(row.quarantined, scale),
        _COLOR_QUARANTINED,
        f"quarantined {row.quarantined}",
        limit=limit,
    )
    _text_node(parent, _MARGIN_LEFT + _PLOT_WIDTH + 8, y + 10, str(row.total))


def _segment(
    parent: ET.Element, x: int, y: int, width: int, color: str, label: str, *, limit: int
) -> int:
    """Emit one bar segment, skipping zero-width rects. Returns the next x.

    ``limit`` is the right edge of the plot. A segment is truncated at it
    rather than allowed to run past, so an inconsistent record cannot paint
    over the labels outside the plot or off the canvas.
    """
    width = min(width, limit - x)
    if width <= 0:
        return x
    rect = ET.SubElement(parent, "rect")
    rect.set("x", str(x))
    rect.set("y", str(y))
    rect.set("width", str(width))
    rect.set("height", str(_BAR_HEIGHT))
    rect.set("fill", color)
    ET.SubElement(rect, "title").text = label
    return x + width


def _text_node(
    parent: ET.Element, x: int, y: int, content: str, *, anchor: str = "start", size: int = 11
) -> ET.Element:
    node = ET.SubElement(parent, "text")
    node.set("x", str(x))
    node.set("y", str(y))
    node.set("font-family", _FONT)
    node.set("font-size", str(size))
    node.set("fill", _COLOR_TEXT)
    node.set("text-anchor", anchor)
    node.text = content
    return node


def render_svg(report: Mapping[str, Any]) -> str:
    """Render a single-snapshot horizontal stacked bar chart.

    One row per issuer in cohort order, on a shared axis whose maximum is
    the largest per-issuer ``documents_ingested``, plus a totals row.

    The totals row is drawn BELOW a separator and on its OWN scale (its own
    ``documents_ingested``), so it reads as a composition bar rather than a
    magnitude comparable to the issuer rows. Putting the cohort total on the
    per-issuer axis would overflow the plot by an order of magnitude; putting
    the issuers on a totals-sized axis would flatten every one of them to a
    few pixels. The separator, the row caption and the ``<desc>`` all say
    which scale is which, and the absolute count is printed at the end of
    every bar either way.

    No trend, no delta, no second data point: n=1 (see module docstring).

    Raises ``RenderError`` for a failure report -- there is nothing to
    chart, and an all-zero chart that could read as "0 problems" is a
    defect, not a degradation.
    """
    if is_failure_report(report):
        raise RenderError("failure reports have no metrics to chart; no SVG is written")

    rows = _chart_rows(report)
    totals_row = _Row("TOTAL", _as_mapping(report.get("totals"), "totals"), "totals")
    axis_max = _axis_maximum(report)
    # Floored at 1 for the same reason as the issuer axis: an all-zero or
    # empty report must not divide by zero.
    totals_scale = max(totals_row.total, 1)
    rows_end = _MARGIN_TOP + len(rows) * _ROW_HEIGHT
    height = rows_end + _FOOTER_HEIGHT
    width = _MARGIN_LEFT + _PLOT_WIDTH + _MARGIN_RIGHT
    label = _text(report.get("label"))
    mode = _text(report.get("mode"))

    # Attribute insertion order is preserved by ET.tostring (verified on
    # CPython 3.11, .python-version), and the committed golden SVG is what
    # catches an interpreter that ever stops preserving it.
    root = ET.Element("svg")
    root.set("xmlns", _SVG_NS)
    root.set("role", "img")
    root.set("viewBox", f"0 0 {width} {height}")
    root.set("width", str(width))
    root.set("height", str(height))

    ET.SubElement(root, "title").text = f"Corpus QA documents by issuer: {label}"
    ET.SubElement(root, "desc").text = (
        f"Horizontal stacked bar chart for the {mode} run {label}. One row per cohort issuer, "
        "in cohort order, on a shared axis of documents; each bar is segmented into "
        "documents_parsed, ingested-but-not-parsed, and documents_quarantined, and the absolute "
        "document count is printed at the end of the bar. The TOTAL row below the separator is "
        "the whole-cohort composition drawn on its own scale, not a magnitude comparable to the "
        "issuer rows. Single snapshot; no time series. A row label marked with an asterisk has "
        f"span_hash_verification_rate {RATE_UNAVAILABLE!r}; its bar is drawn from document counts "
        "only."
    )

    _text_node(root, 16, 24, f"Corpus QA: {label} (mode {mode})", size=13)

    legend = ET.SubElement(root, "g")
    legend.set("id", "legend")
    legend_x = 16
    for color, caption in _LEGEND:
        swatch = ET.SubElement(legend, "rect")
        swatch.set("x", str(legend_x))
        swatch.set("y", "38")
        swatch.set("width", "10")
        swatch.set("height", "10")
        swatch.set("fill", color)
        _text_node(legend, legend_x + 14, 47, caption)
        legend_x += 24 + 7 * len(caption)

    # Gridlines span the issuer rows only: they do not apply to the totals
    # row, which is on its own scale.
    grid = ET.SubElement(root, "g")
    grid.set("id", "axis")
    for tick in range(_TICKS + 1):
        value = (axis_max * tick) // _TICKS
        x = _MARGIN_LEFT + _px(value, axis_max)
        line = ET.SubElement(grid, "line")
        line.set("x1", str(x))
        line.set("y1", str(_MARGIN_TOP - 4))
        line.set("x2", str(x))
        line.set("y2", str(rows_end))
        line.set("stroke", _COLOR_GRID)
        line.set("stroke-width", "1")
        _text_node(grid, x, rows_end + 13, str(value), anchor="middle")
    _text_node(
        grid,
        _MARGIN_LEFT + _PLOT_WIDTH // 2,
        rows_end + 27,
        "documents per issuer",
        anchor="middle",
    )

    bars = ET.SubElement(root, "g")
    bars.set("id", "rows")
    for index, row in enumerate(rows):
        _draw_bar(bars, row, _MARGIN_TOP + index * _ROW_HEIGHT, axis_max)

    totals_group = ET.SubElement(root, "g")
    totals_group.set("id", "totals")
    separator = ET.SubElement(totals_group, "line")
    separator.set("x1", "16")
    separator.set("y1", str(rows_end + 36))
    separator.set("x2", str(width - 16))
    separator.set("y2", str(rows_end + 36))
    separator.set("stroke", _COLOR_GRID)
    separator.set("stroke-width", "1")
    _draw_bar(totals_group, totals_row, rows_end + 44, totals_scale)
    _text_node(
        totals_group,
        _MARGIN_LEFT + _PLOT_WIDTH // 2,
        rows_end + 70,
        "TOTAL: cohort composition, own scale (not comparable to the rows above)",
        anchor="middle",
    )

    if any(row.rate_unavailable for row in (*rows, totals_row)):
        _text_node(root, 16, rows_end + 88, f"* span_hash_verification_rate {RATE_UNAVAILABLE}")

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


# --------------------------------------------------------------------------
# loading + CLI
# --------------------------------------------------------------------------


def check_schema(report: Mapping[str, Any]) -> None:
    """Fail closed on anything but the two schemas this tool renders.

    Deep structural and provenance validation stays owned by
    ``harness.corpus_qa.validate_report``; this is only the gate.
    """
    schema = report.get("schema")
    if schema == FAILURE_SCHEMA:
        return
    if schema != REPORT_SCHEMA:
        raise RenderError(
            f"unsupported schema {schema!r}: expected {REPORT_SCHEMA!r} or {FAILURE_SCHEMA!r}"
        )
    version = report.get("schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise RenderError(
            f"unsupported schema_version {version!r} for {REPORT_SCHEMA!r}: "
            f"expected {REPORT_SCHEMA_VERSION!r}"
        )


def load_report(path: pathlib.Path) -> dict[str, Any]:
    """Read and schema-gate one report. Raises ``RenderError`` for an
    unreadable path, malformed JSON, a non-object document, or a schema this
    tool does not render."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RenderError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RenderError(f"malformed JSON in {path}: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(document, dict):
        raise RenderError(f"{path}: expected a JSON object, got {type(document).__name__}")
    report: dict[str, Any] = document
    check_schema(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render one corpus-QA report to Markdown + SVG.")
    parser.add_argument("report", type=pathlib.Path, help="path to one <label>.json report")
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        required=True,
        help="directory for <report-stem>.md and <report-stem>.svg",
    )
    args = parser.parse_args(argv)

    stem = args.report.stem
    try:
        report = load_report(args.report)
        # Render everything BEFORE writing anything, so a refusal leaves no
        # partial output behind.
        markdown = render_markdown(report)
        svg = None if is_failure_report(report) else render_svg(report)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = args.out_dir / f"{stem}.md"
        markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
        if svg is None:
            print(f"wrote {markdown_path}")  # noqa: T201 -- operator-facing CLI
            # AC5: rendering a failure report is a successful render.
            print(  # noqa: T201
                "corpus-qa-render: failure report: no chart written (no metrics to chart)",
                file=sys.stderr,
            )
            return 0
        svg_path = args.out_dir / f"{stem}.svg"
        svg_path.write_text(svg, encoding="utf-8", newline="\n")
        print(f"wrote {markdown_path}")  # noqa: T201 -- operator-facing CLI
        print(f"wrote {svg_path}")  # noqa: T201 -- operator-facing CLI
    except RenderError as exc:
        print(f"corpus-qa-render: {exc}", file=sys.stderr)  # noqa: T201
        return 2
    except OSError as exc:
        print(f"corpus-qa-render: cannot write output: {exc}", file=sys.stderr)  # noqa: T201
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
