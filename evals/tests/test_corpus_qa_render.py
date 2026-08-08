"""Issue #151: unit tests for the stdlib-only corpus-QA report renderer.

Covers the twelve acceptance criteria in
``docs/research/evals-report-renderer-proposal.md``: Markdown content,
cohort ordering, numeric fidelity, the ``unavailable`` sentinel, the
``corpus-qa-failure/v1`` variant, the fail-closed schema gate, SVG
structure, byte determinism against both committed goldens, the n=1
constraint, the stdlib-only import set, DB/network freedom, and the
``# nosec B405`` bandit gate.

Every test here runs with ``TEST_DATABASE_URL`` unset: the renderer opens no
database and no socket (AC11). The one test that imports ``harness`` does so
inside the test body -- see :func:`test_schema_constants_match_the_harness`.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

import pytest

from reporting import corpus_qa_render as render

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RENDERER_SOURCE = REPO_ROOT / "evals" / "reporting" / "corpus_qa_render.py"
REPORTS_DIR = REPO_ROOT / "evals" / "reports" / "corpus-qa"
COMMITTED_REPORT = REPORTS_DIR / "2026-07-14-synthetic-cohort.json"
GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden" / "corpus-qa"
GOLDEN_MARKDOWN = GOLDEN_DIR / "2026-07-14-synthetic-cohort.md"
GOLDEN_SVG = GOLDEN_DIR / "2026-07-14-synthetic-cohort.svg"

# The renderer's whole permitted import set (AC10). ``xml.etree.ElementTree``
# is the only non-obvious member and is the reason for the # nosec B405.
EXPECTED_IMPORT_ROOTS = frozenset(
    {"__future__", "argparse", "json", "pathlib", "sys", "xml", "collections", "typing"}
)
# Anything that would make the output depend on when or where it ran (AC8).
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {"datetime", "time", "uuid", "random", "os", "secrets", "socket"}
)


# --------------------------------------------------------------------------
# in-memory fixtures
#
# Deliberately NOT written to evals/reports/**: reports are generated
# artifacts and fabricating issuer numbers is prohibited (SCHEMA.md,
# "Regenerating the committed synthetic report").
# --------------------------------------------------------------------------


def issuer(
    ticker: str,
    cik: str,
    *,
    ingested: int = 2,
    parsed: int = 2,
    quarantined: int = 0,
    spans_total: int = 10,
    spans_verified: int = 10,
    rate: str = "1.000000",
    quarantine_reasons: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "cik": cik,
        "entity_id": f"entity-{ticker}",
        "expected_documents": ingested,
        "documents_ingested": ingested,
        "documents_parsed": parsed,
        "documents_quarantined": quarantined,
        "document_versions_parsed": parsed,
        "facts_total": 12,
        "facts_canonical": 10,
        "facts_duplicate": 2,
        "facts_restated": 0,
        "spans_total": spans_total,
        "spans_verified": spans_verified,
        "span_hash_verification_rate": rate,
        "quarantine_reasons": quarantine_reasons or {},
    }


def totals_for(issuers: list[dict[str, Any]], *, rate: str = "1.000000") -> dict[str, Any]:
    def total(field: str) -> int:
        return sum(int(entry[field]) for entry in issuers)

    return {
        "expected_documents": total("expected_documents"),
        "documents_ingested": total("documents_ingested"),
        "documents_parsed": total("documents_parsed"),
        "documents_quarantined": total("documents_quarantined"),
        "document_versions_parsed": total("document_versions_parsed"),
        "facts_total": total("facts_total"),
        "facts_canonical": total("facts_canonical"),
        "facts_duplicate": total("facts_duplicate"),
        "facts_restated": total("facts_restated"),
        "spans_total": total("spans_total"),
        "spans_verified": total("spans_verified"),
        "span_hash_verification_rate": rate,
        "quarantine_reason_distribution": {},
    }


def report(
    issuers: list[dict[str, Any]] | None = None,
    *,
    totals: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    rows = [issuer("AAA", "0000000001")] if issuers is None else issuers
    document: dict[str, Any] = {
        "schema": render.REPORT_SCHEMA,
        "schema_version": render.REPORT_SCHEMA_VERSION,
        "mode": "synthetic",
        "label": "fixture-run",
        "generated_at": "2026-07-14T03:24:12.286619+00:00",
        "provenance_note": "SYNTHETIC RUN: fixture.",
        "run": {
            "run_id": "fixture-run-id",
            "mode": "synthetic",
            "as_of": "2026-07-13",
            "identity_namespace": "fel-corpus-qa-synthetic/v1",
            "expected_issuers": [entry["ticker"] for entry in rows],
        },
        "acceptance": {"accepted": False, "reasons": ["fixture reason"]},
        "cohort": {
            "path": "evals/datasets/issuer-cohort.json",
            "sha256": "0" * 64,
            "as_of": "2026-07-13",
            "issuer_count": len(rows),
        },
        "pipeline": {
            "parser_version": "fel-parser/1.0.0",
            "normalizer_version": "fel-xbrl/1.0.0",
            "queue": "ingestion",
            "jobs_completed": 3,
            "jobs": {
                "discovery_expected": 1,
                "fetch_expected": 2,
                "terminal_counts": {"succeeded": 3},
                "pending": 0,
                "missing_fetch_jobs": [],
                "surplus_fetch_jobs": [],
                "stale_fetch_jobs": [],
                "backlog_after_run": 0,
                "failures": [],
            },
        },
        "issuers": rows,
        "totals": totals if totals is not None else totals_for(rows),
    }
    document.update(overrides)
    return document


def failure_report(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": render.FAILURE_SCHEMA,
        "schema_version": render.REPORT_SCHEMA_VERSION,
        "mode": "live",
        "label": "fixture-failed-run",
        "generated_at": "2026-07-20T11:00:00+00:00",
        "provenance_note": "LIVE RUN: fixture.",
        "run": {
            "run_id": "fixture-failed-id",
            "mode": "live",
            "as_of": "2026-07-19",
            "identity_namespace": "sec-cik",
            "expected_issuers": ["CRM", "NOW"],
        },
        "acceptance": {"accepted": False, "reasons": ["database connection lost mid-run"]},
        "run_failure": {
            "failure_reason": "database connection lost mid-run",
            "jobs_completed": None,
            "jobs": None,
        },
        "cohort": {
            "path": "evals/datasets/issuer-cohort.json",
            "sha256": "f" * 64,
            "as_of": "2026-07-19",
            "issuer_count": 2,
        },
    }
    document.update(overrides)
    return document


def markdown_table_rows(markdown: str, heading: str) -> list[list[str]]:
    """Cells of the table under ``## <heading>``, header and rule excluded."""
    section = markdown.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]


# --------------------------------------------------------------------------
# AC10 / AC8 / AC11 -- the import set is the dependency contract
# --------------------------------------------------------------------------


def renderer_import_roots() -> set[str]:
    tree = ast.parse(RENDERER_SOURCE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_renderer_imports_are_exactly_the_declared_stdlib_set() -> None:
    assert renderer_import_roots() == set(EXPECTED_IMPORT_ROOTS)


def test_every_renderer_import_is_in_the_standard_library() -> None:
    non_stdlib = renderer_import_roots() - set(sys.stdlib_module_names)
    assert non_stdlib == set()


def test_renderer_imports_no_wall_clock_randomness_or_process_state() -> None:
    assert renderer_import_roots() & FORBIDDEN_IMPORT_ROOTS == set()


def test_renderer_imports_no_database_or_network_module() -> None:
    # AC11: a file-in/file-out tool must not drag in a database driver.
    assert renderer_import_roots() & {"psycopg", "fel_workers", "fel_providers", "harness"} == set()


def test_nosec_pragma_is_bare_so_bandit_does_not_read_prose_as_test_ids() -> None:
    source = RENDERER_SOURCE.read_text(encoding="utf-8")
    pragma_lines = [line for line in source.splitlines() if "nosec" in line and "#" in line]
    assert pragma_lines == ["import xml.etree.ElementTree as ET  # nosec B405"]


def test_schema_constants_match_the_harness() -> None:
    # Drift guard. The import lives inside the test body on purpose:
    # harness.corpus_qa pulls in psycopg / fel_workers / fel_providers at
    # module top, and the renderer must never depend on any of them.
    from harness import corpus_qa

    assert render.REPORT_SCHEMA == corpus_qa.REPORT_SCHEMA
    assert render.REPORT_SCHEMA_VERSION == corpus_qa.REPORT_SCHEMA_VERSION
    assert render.FAILURE_SCHEMA == corpus_qa.FAILURE_SCHEMA
    assert render.RATE_UNAVAILABLE == corpus_qa.RATE_UNAVAILABLE


# --------------------------------------------------------------------------
# AC8 -- byte determinism against the committed goldens
# --------------------------------------------------------------------------


def test_markdown_matches_the_committed_golden_byte_for_byte() -> None:
    rendered = render.render_markdown(render.load_report(COMMITTED_REPORT))
    assert rendered == GOLDEN_MARKDOWN.read_text(encoding="utf-8")


def test_svg_matches_the_committed_golden_byte_for_byte() -> None:
    # A committed golden -- not a render-twice assertion -- is what catches
    # cross-version serialization drift, e.g. an interpreter that stops
    # preserving ET.tostring attribute insertion order.
    rendered = render.render_svg(render.load_report(COMMITTED_REPORT))
    assert rendered == GOLDEN_SVG.read_text(encoding="utf-8")


def test_two_independent_renders_are_byte_identical() -> None:
    first = render.load_report(COMMITTED_REPORT)
    second = render.load_report(COMMITTED_REPORT)
    assert render.render_markdown(first) == render.render_markdown(second)
    assert render.render_svg(first) == render.render_svg(second)


# Four seeds rather than two: PYTHONHASHSEED perturbs str/bytes hashing, and on
# an input this small two seeds can happen to agree on iteration order even when
# the renderer is hash-dependent.
DETERMINISM_HASH_SEEDS = ("0", "7", "12345", "99999")

# Runs in a fresh interpreter, so it may not import anything from this module.
_DIGEST_PROGRAM = """\
import hashlib
import pathlib
import sys

from reporting import corpus_qa_render as render

report = render.load_report(pathlib.Path(sys.argv[1]))
for text in (render.render_markdown(report), render.render_svg(report)):
    print(hashlib.sha256(text.encode("utf-8")).hexdigest())
"""


def _digests_under_hash_seed(seed: str) -> str:
    """Render the committed report in a FRESH interpreter at ``PYTHONHASHSEED=seed``."""
    completed = subprocess.run(
        [sys.executable, "-c", _DIGEST_PROGRAM, str(COMMITTED_REPORT)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "evals")},
    )
    return completed.stdout


def test_output_is_identical_across_hash_seeds_in_separate_processes() -> None:
    """The only check here that can catch hash-order dependence.

    ``PYTHONHASHSEED`` is fixed for an interpreter's lifetime, so
    :func:`test_two_independent_renders_are_byte_identical` renders twice under
    one seed and agrees with itself however the renderer iterates. Replace a
    ``sorted(...)`` with bare ``set`` iteration and that test still passes;
    this one fails. Separate processes at differing seeds are the only way to
    observe the difference, which is why the guarantee cannot be asserted
    in-process no matter how many times a single interpreter re-renders.
    """
    by_seed = {seed: _digests_under_hash_seed(seed) for seed in DETERMINISM_HASH_SEEDS}
    detail = "\n".join(
        f"  seed {seed}: {digests.split()}" for seed, digests in sorted(by_seed.items())
    )
    assert (
        len(set(by_seed.values())) == 1
    ), f"renderer output depends on PYTHONHASHSEED -- iteration is hash-ordered:\n{detail}"


def test_goldens_end_with_exactly_one_newline_and_use_unix_line_endings() -> None:
    for golden in (GOLDEN_MARKDOWN, GOLDEN_SVG):
        raw = golden.read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"\n")
        assert not raw.endswith(b"\n\n")


def test_generated_at_is_the_only_timestamp_and_is_copied_verbatim() -> None:
    markdown = render.render_markdown(report(generated_at="2020-01-02T03:04:05.678901+00:00"))
    assert "| `generated_at` | `2020-01-02T03:04:05.678901+00:00` |" in markdown
    # Exactly one ISO-8601 stamp in the whole document: no "rendered at".
    stamps = re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", markdown)
    assert stamps == ["2020-01-02T03:04:05"]


# --------------------------------------------------------------------------
# AC1 -- Markdown content
# --------------------------------------------------------------------------


def test_synthetic_banner_states_the_report_is_not_an_acceptance_artifact() -> None:
    markdown = render.render_markdown(report())
    banner = markdown.split("## Provenance", 1)[0]
    assert "NOT AN ACCEPTANCE ARTIFACT" in banner
    assert "never acceptance-grade" in banner
    assert "Mode: `synthetic`. Accepted: **no**." in banner


def test_live_accepted_banner_differs_from_the_synthetic_one() -> None:
    document = report(mode="live", acceptance={"accepted": True, "reasons": []})
    banner = render.render_markdown(document).split("## Provenance", 1)[0]
    assert "**LIVE RUN.**" in banner
    assert "Accepted: **yes**." in banner
    assert "NOT AN ACCEPTANCE ARTIFACT" not in banner


def test_provenance_note_is_a_blockquote_and_survives_multiple_lines() -> None:
    note = "first line\n\nsecond | line"
    markdown = render.render_markdown(report(provenance_note=note))
    banner = markdown.split("## Provenance", 1)[0]
    # Not collapsed into a cell: the pipe is NOT escaped and the break holds.
    assert "> first line\n>\n> second | line" in banner


def test_provenance_block_carries_every_required_field() -> None:
    markdown = render.render_markdown(render.load_report(COMMITTED_REPORT))
    rows = dict(markdown_table_rows(markdown, "Provenance"))
    assert rows["`label`"] == "`2026-07-14-synthetic-cohort`"
    assert rows["`run.run_id`"] == "`11f525301ba04b468516f2051ba5419a`"
    assert rows["`run.identity_namespace`"] == "`fel-corpus-qa-synthetic/v1`"
    assert rows["`cohort.sha256`"] == (
        "`3fda084f60f4fd00225d36e0e6233ac03d0f2ff4420cad1b9d2ef95cf72e4b4c`"
    )
    assert rows["`cohort.issuer_count`"] == "20"
    assert rows["`pipeline.parser_version`"] == "`fel-parser/1.0.0`"
    assert rows["`pipeline.normalizer_version`"] == "`fel-xbrl/1.0.0`"
    assert rows["`pipeline.queue`"] == "`ingestion`"
    assert rows["`pipeline.jobs_completed`"] == "70"


def test_acceptance_block_lists_every_reason_in_order() -> None:
    document = report(acceptance={"accepted": False, "reasons": ["zeta reason", "alpha reason"]})
    markdown = render.render_markdown(document)
    section = markdown.split("## Acceptance\n", 1)[1].split("\n## ", 1)[0]
    assert section.strip().splitlines() == [
        "Accepted: **no**",
        "",
        "- zeta reason",
        "- alpha reason",
    ]


def test_totals_table_lists_all_twelve_scalar_fields() -> None:
    markdown = render.render_markdown(render.load_report(COMMITTED_REPORT))
    rows = markdown_table_rows(markdown, "Totals")
    assert [row[0] for row in rows] == [
        "`expected_documents`",
        "`documents_ingested`",
        "`documents_parsed`",
        "`documents_quarantined`",
        "`document_versions_parsed`",
        "`facts_total`",
        "`facts_canonical`",
        "`facts_duplicate`",
        "`facts_restated`",
        "`spans_total`",
        "`spans_verified`",
        "`span_hash_verification_rate`",
    ]
    assert dict(rows)["`documents_parsed`"] == "44"
    assert dict(rows)["`span_hash_verification_rate`"] == "`1.000000`"


def test_issuer_table_has_the_thirteen_specified_columns_and_exact_first_row() -> None:
    markdown = render.render_markdown(render.load_report(COMMITTED_REPORT))
    section = markdown.split("## Per-issuer metrics\n", 1)[1]
    header = next(line for line in section.splitlines() if line.startswith("|"))
    assert [cell.strip() for cell in header.strip("|").split("|")] == list(render.ISSUER_COLUMNS)
    first = markdown_table_rows(markdown, "Per-issuer metrics")[0]
    assert first == [
        "`CRM`",
        "`0001108524`",
        "3",
        "3",
        "3",
        "0",
        "18",
        "15",
        "3",
        "2",
        "39",
        "39",
        "`1.000000`",
    ]


def test_issuer_table_omits_the_columns_the_spec_leaves_out() -> None:
    # entity_id and document_versions_parsed are per-issuer schema fields
    # that AC1.5 deliberately excludes from the table.
    assert "entity_id" not in render.ISSUER_COLUMNS
    assert "document_versions_parsed" not in render.ISSUER_COLUMNS


def test_quarantine_table_is_sorted_by_reason_code() -> None:
    totals = totals_for([issuer("AAA", "0000000001")])
    totals["quarantine_reason_distribution"] = {"UNKNOWN_FORMAT": 3, "ALPHA_REASON": 1}
    markdown = render.render_markdown(report(totals=totals))
    # Insertion order is FORMAT-then-ALPHA; render order is sorted.
    assert markdown_table_rows(markdown, "Quarantine reasons") == [
        ["`ALPHA_REASON`", "1"],
        ["`UNKNOWN_FORMAT`", "3"],
    ]


def test_quarantine_section_renders_none_when_the_distribution_is_empty() -> None:
    markdown = render.render_markdown(report())
    section = markdown.split("## Quarantine reasons\n", 1)[1].split("\n## ", 1)[0]
    assert section.strip() == "none"


def test_jobs_table_reports_scalars_sorted_terminal_counts_and_array_lengths() -> None:
    document = report()
    document["pipeline"]["jobs"] = {
        "discovery_expected": 2,
        "fetch_expected": 5,
        "terminal_counts": {"succeeded": 4, "failed": 1},
        "pending": 1,
        "missing_fetch_jobs": ["0001-24-000001"],
        "surplus_fetch_jobs": [{"job_id": "j1"}, {"job_id": "j2"}],
        "stale_fetch_jobs": [],
        "backlog_after_run": 7,
        "failures": [{"job_id": "j3"}],
    }
    rows = dict(markdown_table_rows(render.render_markdown(document), "Jobs"))
    assert rows["`discovery_expected`"] == "2"
    assert rows["`fetch_expected`"] == "5"
    assert rows["`pending`"] == "1"
    # sorted() key order: "failed" before "succeeded", not insertion order.
    assert rows["`terminal_counts`"] == "`failed=1, succeeded=4`"
    assert rows["`backlog_after_run`"] == "7"
    assert rows["`missing_fetch_jobs (count)`"] == "1"
    assert rows["`surplus_fetch_jobs (count)`"] == "2"
    assert rows["`stale_fetch_jobs (count)`"] == "0"
    assert rows["`failures (count)`"] == "1"


def test_jobs_section_says_not_accounted_when_the_pipeline_has_no_jobs_object() -> None:
    document = report()
    del document["pipeline"]["jobs"]
    section = render.render_markdown(document).split("## Jobs\n", 1)[1]
    assert section.strip() == "not accounted"


# --------------------------------------------------------------------------
# AC2 -- cohort order, never value order
# --------------------------------------------------------------------------


def test_issuer_rows_keep_cohort_order_and_are_not_ranked() -> None:
    rows = [
        issuer("ZZZ", "0000000003", ingested=1, parsed=1),
        issuer("AAA", "0000000001", ingested=9, parsed=9),
        issuer("MMM", "0000000002", ingested=5, parsed=5),
    ]
    markdown = render.render_markdown(report(rows))
    rendered = [row[0] for row in markdown_table_rows(markdown, "Per-issuer metrics")]
    assert rendered == ["`ZZZ`", "`AAA`", "`MMM`"]
    # Explicitly neither alphabetical nor worst/best-first.
    assert rendered != sorted(rendered)
    assert rendered != ["`AAA`", "`MMM`", "`ZZZ`"]


def test_expected_issuers_keep_cohort_order() -> None:
    document = report(run={"run_id": "r", "expected_issuers": ["ZZZ", "AAA", "MMM"]})
    markdown = render.render_markdown(document)
    assert "| `run.expected_issuers` | `ZZZ, AAA, MMM` |" in markdown


def test_svg_rows_keep_cohort_order() -> None:
    rows = [
        issuer("ZZZ", "0000000003"),
        issuer("AAA", "0000000001"),
        issuer("MMM", "0000000002"),
    ]
    svg = render.render_svg(report(rows))
    assert re.findall(r">(ZZZ|AAA|MMM|TOTAL)<", svg) == ["ZZZ", "AAA", "MMM", "TOTAL"]


# --------------------------------------------------------------------------
# AC3 -- numeric fidelity
# --------------------------------------------------------------------------


def test_cik_zero_padding_survives_inside_a_backtick_fence() -> None:
    markdown = render.render_markdown(report([issuer("AAA", "0001108524")]))
    assert "| `AAA` | `0001108524` |" in markdown
    # A bare 1108524 anywhere would mean something int()-coerced the cik.
    assert "1108524" in markdown
    assert re.search(r"\|\s*1108524\s*\|", markdown) is None


def test_rate_string_is_echoed_verbatim_and_never_reformatted() -> None:
    rows = [issuer("AAA", "0000000001", rate="0.987654")]
    markdown = render.render_markdown(report(rows, totals=totals_for(rows, rate="0.987654")))
    assert "`0.987654`" in markdown
    for reformatted in ("98.77", "98.8%", "0.99", "0.9877"):
        assert reformatted not in markdown


def test_pipe_characters_in_cell_values_are_escaped() -> None:
    document = report(pipeline={"parser_version": "fel|parser", "jobs_completed": 1})
    markdown = render.render_markdown(document)
    assert r"| `pipeline.parser_version` | `fel\|parser` |" in markdown


def test_newlines_in_cell_values_are_collapsed_to_spaces() -> None:
    document = report(pipeline={"queue": "line one\nline two", "jobs_completed": 1})
    markdown = render.render_markdown(document)
    assert "| `pipeline.queue` | `line one line two` |" in markdown


def test_backtick_bearing_values_get_a_wider_fence() -> None:
    markdown = render.render_markdown(report([issuer("A`B", "0000000001")]))
    assert "| ``A`B`` |" in markdown


def test_boolean_and_null_values_render_as_json_tokens_not_python_ones() -> None:
    document = report(pipeline={"queue": None, "jobs_completed": True})
    markdown = render.render_markdown(document)
    assert "| `pipeline.queue` | null |" in markdown
    assert "| `pipeline.jobs_completed` | true |" in markdown
    assert "None" not in markdown
    assert "True" not in markdown


# --------------------------------------------------------------------------
# AC4 -- the "unavailable" sentinel
# --------------------------------------------------------------------------


def unavailable_fixture() -> dict[str, Any]:
    """Two issuers, one with zero spans. The committed report exercises
    none of this: all 20 of its issuers have spans_total > 0."""
    rows = [
        issuer("AAA", "0000000001", ingested=4, parsed=4, spans_total=10, spans_verified=10),
        issuer(
            "BBB",
            "0000000002",
            ingested=2,
            parsed=0,
            quarantined=2,
            spans_total=0,
            spans_verified=0,
            rate=render.RATE_UNAVAILABLE,
        ),
    ]
    return report(rows, totals=totals_for(rows, rate="1.000000"))


def test_unavailable_rate_is_printed_as_the_literal_token() -> None:
    markdown = render.render_markdown(unavailable_fixture())
    rows = markdown_table_rows(markdown, "Per-issuer metrics")
    assert rows[1][0] == "`BBB`"
    assert rows[1][-1] == "`unavailable`"


def test_unavailable_rate_is_never_rendered_as_zero_full_or_blank() -> None:
    markdown = render.render_markdown(unavailable_fixture())
    row = markdown_table_rows(markdown, "Per-issuer metrics")[1]
    assert row[-1] not in {"0.000000", "`0.000000`", "100%", "`1.000000`", "-", "", "—"}
    assert "0.000000" not in markdown
    assert "%" not in markdown


def test_totals_rate_is_echoed_not_recomputed_from_the_issuer_rows() -> None:
    # A renderer that derived its own rate would have to decide what an
    # unavailable issuer contributes. This one echoes totals as given.
    rows = [issuer("AAA", "0000000001", spans_total=0, spans_verified=0, rate="unavailable")]
    document = report(rows, totals=totals_for(rows, rate="unavailable"))
    totals = dict(markdown_table_rows(render.render_markdown(document), "Totals"))
    assert totals["`span_hash_verification_rate`"] == "`unavailable`"


def test_unavailable_issuer_bar_is_drawn_from_document_counts_and_marked() -> None:
    svg = render.render_svg(unavailable_fixture())
    # axis_max = 4 (AAA), plot width 480 -> 120px per document.
    # Row 1 (BBB) sits at y = 72 + 1*20 = 92; its 2 quarantined documents
    # are a 240px bar, so a missing RATE is neither a zero-height nor a
    # full-height BAR.
    assert '<rect x="128" y="92" width="240" height="12" fill="#a33a3a">' in svg
    # AAA's rate IS available, so only BBB carries the marker.
    assert ">BBB *<" in svg
    assert ">AAA<" in svg
    assert ">AAA *<" not in svg
    assert "* span_hash_verification_rate unavailable" in svg


def test_no_unavailable_footnote_when_every_rate_is_present() -> None:
    svg = render.render_svg(render.load_report(COMMITTED_REPORT))
    assert "* span_hash_verification_rate unavailable" not in svg
    assert " *<" not in svg


# --------------------------------------------------------------------------
# AC5 -- the corpus-qa-failure/v1 sibling
# --------------------------------------------------------------------------


def test_failure_report_is_dispatched_on_schema_not_filename() -> None:
    assert render.is_failure_report(failure_report()) is True
    assert render.is_failure_report(report()) is False


def test_failure_markdown_has_the_banner_reason_and_shared_provenance() -> None:
    markdown = render.render_markdown(failure_report())
    assert markdown.startswith("# Corpus QA run failure: `fixture-failed-run`\n")
    assert "> **RUN FAILURE." in markdown
    assert "- `failure_reason`: database connection lost mid-run" in markdown
    assert "- database connection lost mid-run" in markdown  # acceptance reason
    provenance = dict(markdown_table_rows(markdown, "Provenance"))
    assert provenance["`run.run_id`"] == "`fixture-failed-id`"
    assert provenance["`cohort.issuer_count`"] == "2"


def test_failure_markdown_has_no_metrics_sections() -> None:
    markdown = render.render_markdown(failure_report())
    for absent in ("## Totals", "## Per-issuer metrics", "## Quarantine reasons"):
        assert absent not in markdown


def test_failure_markdown_reports_not_accounted_for_null_jobs() -> None:
    section = render.render_markdown(failure_report()).split("## Jobs\n", 1)[1]
    assert "- `jobs_completed`: not accounted" in section
    assert "- `jobs`: not accounted" in section
    # A table of zeroes here could read as "no problems".
    assert "backlog_after_run" not in section


def test_failure_markdown_renders_the_jobs_table_when_it_was_accounted() -> None:
    document = failure_report(
        run_failure={
            "failure_reason": "iteration budget exhausted",
            "jobs_completed": 12,
            "jobs": {
                "discovery_expected": 2,
                "fetch_expected": 5,
                "terminal_counts": {"succeeded": 3, "queued": 2},
                "pending": 2,
                "missing_fetch_jobs": [],
                "surplus_fetch_jobs": [],
                "stale_fetch_jobs": [],
                "backlog_after_run": 2,
                "failures": [],
            },
        }
    )
    markdown = render.render_markdown(document)
    assert "- `jobs_completed`: 12" in markdown
    rows = dict(markdown_table_rows(markdown, "Jobs"))
    assert rows["`pending`"] == "2"
    assert rows["`terminal_counts`"] == "`queued=2, succeeded=3`"


def test_render_svg_refuses_a_failure_report() -> None:
    with pytest.raises(render.RenderError) as excinfo:
        render.render_svg(failure_report())
    assert "no metrics to chart" in str(excinfo.value)


# --------------------------------------------------------------------------
# AC6 -- fail-closed schema gate
# --------------------------------------------------------------------------


def test_schema_gate_accepts_both_supported_schemas() -> None:
    # Neither call raises. The refusals are covered by the negative cases below.
    render.check_schema(report())
    render.check_schema(failure_report())
    assert render.load_report(COMMITTED_REPORT)["schema"] == render.REPORT_SCHEMA


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        ({"schema": "nope", "schema_version": 9}, "unsupported schema 'nope'"),
        ({"schema_version": 1}, "unsupported schema None"),
        (
            {"schema": "corpus-qa-report/v1", "schema_version": 2},
            "unsupported schema_version 2",
        ),
        (
            {"schema": "corpus-qa-report/v1", "schema_version": "1"},
            "unsupported schema_version '1'",
        ),
        ({"schema": "corpus-qa-report/v1"}, "unsupported schema_version None"),
    ],
)
def test_schema_gate_refuses_anything_else(document: dict[str, Any], fragment: str) -> None:
    with pytest.raises(render.RenderError) as excinfo:
        render.check_schema(document)
    assert fragment in str(excinfo.value)


def test_load_report_refuses_a_missing_file(tmp_path: pathlib.Path) -> None:
    with pytest.raises(render.RenderError) as excinfo:
        render.load_report(tmp_path / "absent.json")
    assert "cannot read" in str(excinfo.value)


def test_load_report_refuses_malformed_json(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schema": "corpus-qa-report/v1",', encoding="utf-8")
    with pytest.raises(render.RenderError) as excinfo:
        render.load_report(path)
    assert "malformed JSON" in str(excinfo.value)


def test_load_report_refuses_a_json_document_that_is_not_an_object(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(render.RenderError) as excinfo:
        render.load_report(path)
    assert "expected a JSON object" in str(excinfo.value)


def test_load_report_accepts_the_committed_report() -> None:
    document = render.load_report(COMMITTED_REPORT)
    assert document["schema"] == "corpus-qa-report/v1"
    assert document["schema_version"] == 1
    assert len(document["issuers"]) == 20


def test_malformed_metrics_raise_a_clean_render_error_not_a_traceback() -> None:
    rows = [issuer("AAA", "0000000001")]
    rows[0]["documents_ingested"] = "3"
    with pytest.raises(render.RenderError) as excinfo:
        render.render_svg(report(rows))
    assert "issuers[0].documents_ingested: expected an integer, got str" in str(excinfo.value)


def test_missing_issuers_array_raises_a_clean_render_error() -> None:
    document = report()
    document["issuers"] = {}
    with pytest.raises(render.RenderError) as excinfo:
        render.render_markdown(document)
    assert "issuers: expected an array" in str(excinfo.value)


# --------------------------------------------------------------------------
# AC7 -- SVG structure
# --------------------------------------------------------------------------


def test_svg_preamble_and_root_attributes_are_exact() -> None:
    svg = render.render_svg(render.load_report(COMMITTED_REPORT))
    head = svg.splitlines()[:2]
    assert head[0] == '<?xml version="1.0" encoding="UTF-8"?>'
    # 20 issuers -> height 72 + 20*20 + 96 = 568; width 128 + 480 + 64 = 672.
    assert head[1] == (
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        'viewBox="0 0 672 568" width="672" height="568">'
    )


def test_svg_carries_title_and_desc_for_accessibility() -> None:
    svg = render.render_svg(render.load_report(COMMITTED_REPORT))
    assert "<title>Corpus QA documents by issuer: 2026-07-14-synthetic-cohort</title>" in svg
    assert "<desc>Horizontal stacked bar chart for the synthetic run" in svg


def test_every_svg_coordinate_is_an_integer() -> None:
    svg = render.render_svg(render.load_report(COMMITTED_REPORT))
    geometry = re.findall(r'\b(x|y|width|height|x1|y1|x2|y2)="([^"]*)"', svg)
    assert geometry  # the regex must actually be finding coordinates
    for name, value in geometry:
        assert re.fullmatch(r"-?\d+", value), f"non-integer {name}={value!r}"


def test_svg_has_no_external_reference_or_stylesheet() -> None:
    svg = render.render_svg(render.load_report(COMMITTED_REPORT))
    for forbidden in ("http://", "https://", "@import", "<style", "<image", "url(", "%"):
        occurrences = svg.count(forbidden)
        # The xmlns declaration is the single permitted "http://".
        assert occurrences == (1 if forbidden == "http://" else 0), forbidden
    assert 'font-family="monospace"' in svg


def test_axis_maximum_is_the_largest_issuer_ingest_count() -> None:
    rows = [
        issuer("AAA", "0000000001", ingested=1, parsed=1),
        issuer("BBB", "0000000002", ingested=5, parsed=5),
    ]
    svg = render.render_svg(report(rows))
    # ticks at 0, 5//4=1, 10//4=2, 15//4=3, 5
    assert re.findall(r'text-anchor="middle">(\d+)</text>', svg)[:5] == ["0", "1", "2", "3", "5"]
    # AAA is 1 of 5 -> 480//5 = 96px.
    assert '<rect x="128" y="72" width="96" height="12" fill="#2f6f4f">' in svg


def test_empty_issuer_list_floors_the_axis_at_one_instead_of_dividing_by_zero() -> None:
    document = report([], totals=totals_for([]))
    svg = render.render_svg(document)
    assert 'viewBox="0 0 672 168"' in svg  # 72 + 0 + 96
    assert ">TOTAL<" in svg


def test_all_zero_report_floors_the_axis_at_one() -> None:
    rows = [issuer("AAA", "0000000001", ingested=0, parsed=0, spans_total=0, rate="unavailable")]
    svg = render.render_svg(report(rows, totals=totals_for(rows, rate="unavailable")))
    # Axis floored at 1: every tick collapses to 0 except the last.
    assert re.findall(r'text-anchor="middle">(\d+)</text>', svg)[:5] == ["0", "0", "0", "0", "1"]
    # No bar of any colour: zero-width segments are not emitted at all.
    assert "<rect" not in svg.split('id="rows"', 1)[1]


def test_segments_are_clamped_so_inconsistent_counts_cannot_go_negative() -> None:
    rows = [issuer("AAA", "0000000001", ingested=2, parsed=2, quarantined=2)]
    svg = render.render_svg(report(rows, totals=totals_for(rows)))
    assert 'width="-' not in svg


def test_totals_row_is_separated_and_drawn_on_its_own_scale() -> None:
    rows = [
        issuer("AAA", "0000000001", ingested=4, parsed=4),
        issuer("BBB", "0000000002", ingested=2, parsed=0, quarantined=2),
    ]
    svg = render.render_svg(report(rows, totals=totals_for(rows)))
    # rows_end = 72 + 2*20 = 112; separator at 148; totals bar at y=156.
    assert '<line x1="16" y1="148" x2="656" y2="148"' in svg
    # totals scale = 6 documents -> parsed 4 is 4*480//6 = 320px, which would
    # have been 480px (a full-width overflow) on the per-issuer axis of 4.
    assert '<rect x="128" y="156" width="320" height="12" fill="#2f6f4f">' in svg
    assert "TOTAL: cohort composition, own scale" in svg


# --------------------------------------------------------------------------
# AC9 -- n = 1
# --------------------------------------------------------------------------


def test_cli_accepts_exactly_one_report_and_has_no_comparison_flag() -> None:
    with pytest.raises(SystemExit) as excinfo:
        render.main(["a.json", "b.json", "--out-dir", "out"])
    assert excinfo.value.code == 2
    for flag in ("--compare", "--since", "--baseline", "--glob", "--reports-dir"):
        with pytest.raises(SystemExit):
            render.main([str(COMMITTED_REPORT), flag, "x"])


def test_output_has_no_trend_or_delta_vocabulary() -> None:
    document = render.load_report(COMMITTED_REPORT)
    combined = render.render_markdown(document) + render.render_svg(document)
    for word in ("trend", "delta", "since", "previous", "change vs", "sparkline", "▲", "▼"):
        assert word not in combined


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_writes_both_outputs_and_exits_zero(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "nested" / "out"
    code = render.main([str(COMMITTED_REPORT), "--out-dir", str(out)])
    assert code == 0
    markdown = out / "2026-07-14-synthetic-cohort.md"
    svg = out / "2026-07-14-synthetic-cohort.svg"
    assert markdown.read_text(encoding="utf-8") == GOLDEN_MARKDOWN.read_text(encoding="utf-8")
    assert svg.read_text(encoding="utf-8") == GOLDEN_SVG.read_text(encoding="utf-8")
    assert capsys.readouterr().err == ""


def test_cli_output_names_come_from_the_input_stem_not_the_report_label(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "renamed.json"
    source.write_text(COMMITTED_REPORT.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out"
    assert render.main([str(source), "--out-dir", str(out)]) == 0
    assert sorted(path.name for path in out.iterdir()) == ["renamed.md", "renamed.svg"]


def test_cli_refuses_an_unsupported_schema_with_exit_2_and_writes_nothing(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema":"nope","schema_version":9}', encoding="utf-8")
    out = tmp_path / "out"
    assert render.main([str(bad), "--out-dir", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "corpus-qa-render: unsupported schema 'nope': expected 'corpus-qa-report/v1' "
        "or 'corpus-qa-failure/v1'"
    ]
    assert "Traceback" not in captured.err
    assert not out.exists()


def test_cli_writes_markdown_only_for_a_failure_report_and_still_exits_zero(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    source = tmp_path / "failed-run.json"
    source.write_text(json.dumps(failure_report()), encoding="utf-8")
    out = tmp_path / "out"
    assert render.main([str(source), "--out-dir", str(out)]) == 0
    assert [path.name for path in out.iterdir()] == ["failed-run.md"]
    assert "no chart written" in capsys.readouterr().err
