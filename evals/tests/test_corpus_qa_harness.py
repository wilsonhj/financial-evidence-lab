"""T0112: corpus-QA harness tests — the synthetic cohort run end-to-end
through the REAL pipeline, the report schema, and the committed acceptance
artifact.

The synthetic plan (harness.synthetic_sec) is deterministic, so the
expected corpus-quality metrics are known exactly:

- 20 issuers x (10-K + 10-Q)                        = 40 clean filings
- issuers 0, 5, 10, 15: a 10-Q/A amendment          = +4 parsed filings
- issuers 3, 10, 17: an UNKNOWN_CONTEXT corrupt doc = +3 quarantined
- issuers 5, 12, 19: an UNKNOWN_FORMAT corrupt doc  = +3 quarantined

=> 50 documents ingested, 44 parsed, 6 quarantined; one duplicated
revenue presentation per parsed filing (44 duplicates); each amendment
restates its Q1 revenue on the canonical + duplicate rows (8 restated).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from harness.corpus_qa import (
    DEFAULT_COHORT_PATH,
    HarnessError,
    load_cohort,
    run_corpus_qa,
    validate_report,
)
from harness.synthetic_sec import SyntheticCohortSecClient, build_plan, render_filing

REPORTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "reports" / "corpus-qa"

EXPECTED_ISSUERS = 20
EXPECTED_DOCUMENTS = 50
EXPECTED_PARSED = 44
EXPECTED_QUARANTINED = 6
EXPECTED_DUPLICATES = 44
EXPECTED_RESTATED = 8
EXPECTED_QUARANTINE_DISTRIBUTION = {"UNKNOWN_CONTEXT": 3, "UNKNOWN_FORMAT": 3}


# ---------------------------------------------------------------------------
# Deterministic synthetic corpus (no DB, no network).
# ---------------------------------------------------------------------------


def test_synthetic_client_is_deterministic_and_labeled() -> None:
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    ciks = [issuer["cik"] for issuer in cohort.issuers]
    first, second = SyntheticCohortSecClient(ciks), SyntheticCohortSecClient(ciks)
    for cik in ciks:
        assert first.submissions(cik) == second.submissions(cik)
        for index, filing in enumerate(build_plan(cik, ciks.index(cik))):
            del index
            rendered = render_filing(filing)
            assert rendered == render_filing(filing), "same inputs, same bytes"
            assert b"SYNTHETIC" in rendered, "every synthetic document is labeled"
            assert cik.encode() in rendered


def test_synthetic_plan_matches_documented_expectations() -> None:
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    assert len(cohort.issuers) == EXPECTED_ISSUERS
    plans = [build_plan(issuer["cik"], index) for index, issuer in enumerate(cohort.issuers)]
    total = sum(len(plan) for plan in plans)
    assert total == EXPECTED_DOCUMENTS
    accessions = [filing.accession for plan in plans for filing in plan]
    assert len(set(accessions)) == total, "accessions are globally unique"
    amendments = [f for plan in plans for f in plan if f.form == "10-Q/A"]
    assert len(amendments) == 4
    for amendment in amendments:
        assert amendment.revenue_offset != 0, "amendments must change the revenue"


# ---------------------------------------------------------------------------
# End-to-end synthetic run through the real pipeline (DB-backed).
# ---------------------------------------------------------------------------


@pytest.fixture()
def synthetic_report(qa_database_url: str, tmp_path: pathlib.Path) -> dict[str, object]:
    path = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="test-synthetic",
    )
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    return payload


def test_synthetic_run_records_expected_corpus_quality_metrics(
    synthetic_report: dict[str, object],
) -> None:
    validate_report(synthetic_report)  # schema-valid by construction
    assert synthetic_report["mode"] == "synthetic"
    assert "SYNTHETIC" in str(synthetic_report["provenance_note"])
    issuers = synthetic_report["issuers"]
    totals = synthetic_report["totals"]
    assert len(issuers) == EXPECTED_ISSUERS  # type: ignore[arg-type]
    assert totals["documents_ingested"] == EXPECTED_DOCUMENTS  # type: ignore[index]
    assert totals["documents_parsed"] == EXPECTED_PARSED  # type: ignore[index]
    assert totals["documents_quarantined"] == EXPECTED_QUARANTINED  # type: ignore[index]
    assert totals["facts_duplicate"] == EXPECTED_DUPLICATES  # type: ignore[index]
    assert totals["facts_restated"] == EXPECTED_RESTATED  # type: ignore[index]
    assert (
        totals["quarantine_reason_distribution"]  # type: ignore[index]
        == EXPECTED_QUARANTINE_DISTRIBUTION
    )
    assert totals["facts_total"] > 0  # type: ignore[index]


def test_synthetic_run_span_hashes_all_verify(synthetic_report: dict[str, object]) -> None:
    """Citation integrity: 100% of persisted span hashes re-verify against
    the canonical text the pipeline stored — per issuer and in total."""
    totals = synthetic_report["totals"]
    assert totals["spans_total"] > 0  # type: ignore[index]
    assert totals["spans_verified"] == totals["spans_total"]  # type: ignore[index]
    assert totals["span_hash_verification_rate"] == "1.000000"  # type: ignore[index]
    for issuer in synthetic_report["issuers"]:  # type: ignore[union-attr]
        assert issuer["spans_verified"] == issuer["spans_total"]
        assert issuer["span_hash_verification_rate"] == "1.000000"


def test_synthetic_run_per_issuer_shape(synthetic_report: dict[str, object]) -> None:
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    by_cik = {issuer["cik"]: issuer for issuer in synthetic_report["issuers"]}  # type: ignore[union-attr]
    for index, member in enumerate(cohort.issuers):
        metrics = by_cik[member["cik"]]
        assert metrics["ticker"] == member["ticker"]
        expected_parsed = 2 + (1 if index % 5 == 0 else 0)
        expected_quarantined = (1 if index % 7 == 3 else 0) + (1 if index % 7 == 5 else 0)
        assert metrics["documents_parsed"] == expected_parsed, member
        assert metrics["documents_quarantined"] == expected_quarantined, member
        assert metrics["documents_ingested"] == expected_parsed + expected_quarantined
        assert metrics["facts_duplicate"] == expected_parsed
        assert metrics["facts_restated"] == (2 if index % 5 == 0 else 0), member
        assert metrics["facts_total"] > 0


def test_rerun_is_idempotent_and_reproduces_identical_metrics(
    qa_database_url: str, tmp_path: pathlib.Path
) -> None:
    """T0111c meets T0112: replaying the whole cohort run on the same
    database is a corpus no-op — the recorded metrics are identical."""
    blobs = tmp_path / "blobs"  # durable across the two passes
    first_path = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="run-one",
        storage_dir=blobs,
    )
    second_path = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="run-two",
        storage_dir=blobs,
    )
    first = json.loads(first_path.read_text())
    second = json.loads(second_path.read_text())
    assert first["issuers"] == second["issuers"]
    assert first["totals"] == second["totals"]
    assert first["cohort"] == second["cohort"]


def test_cohort_file_is_never_modified(qa_database_url: str, tmp_path: pathlib.Path) -> None:
    before = DEFAULT_COHORT_PATH.read_bytes()
    run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="read-only-check",
    )
    assert DEFAULT_COHORT_PATH.read_bytes() == before


# ---------------------------------------------------------------------------
# Report schema validation + the committed acceptance artifact.
# ---------------------------------------------------------------------------


def test_validate_report_fails_closed() -> None:
    with pytest.raises(HarnessError, match="schema"):
        validate_report({"schema": "other/v9"})
    good = {
        "schema": "corpus-qa-report/v1",
        "schema_version": 1,
        "mode": "practice",
    }
    with pytest.raises(HarnessError, match="mode"):
        validate_report(good)


def test_committed_synthetic_report_is_schema_valid_and_labeled() -> None:
    """The committed T0112 acceptance artifact must validate and must be
    unambiguously labeled synthetic."""
    committed = sorted(REPORTS_DIR.glob("*-synthetic-*.json"))
    assert committed, f"no committed synthetic corpus-qa report under {REPORTS_DIR}"
    for path in committed:
        report = json.loads(path.read_text())
        validate_report(report)
        assert report["mode"] == "synthetic"
        assert "SYNTHETIC" in report["provenance_note"]
        assert report["cohort"]["issuer_count"] == EXPECTED_ISSUERS
        assert report["totals"]["span_hash_verification_rate"] == "1.000000"
        # The committed artifact pins the exact cohort file it measured.
        cohort = load_cohort(DEFAULT_COHORT_PATH)
        assert report["cohort"]["sha256"] == cohort.sha256
