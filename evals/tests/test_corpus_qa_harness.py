"""T0112: corpus-QA harness tests — the synthetic cohort run end-to-end
through the REAL pipeline, the fail-closed destructive-reset and live-SEC
identity gates, per-run provenance/metric scoping, the report schema, and
the committed synthetic artifact.

The synthetic plan (harness.synthetic_sec) is deterministic, so the
expected corpus-quality metrics are known exactly:

- 20 issuers x (10-K + 10-Q)                        = 40 clean filings
- issuers 0, 5, 10, 15: a 10-Q/A amendment          = +4 parsed filings
- issuers 3, 10, 17: an UNKNOWN_CONTEXT corrupt doc = +3 quarantined
- issuers 5, 12, 19: an UNKNOWN_FORMAT corrupt doc  = +3 quarantined

=> 50 documents ingested, 44 parsed, 6 quarantined; one duplicated
revenue presentation per parsed filing (44 duplicates); each amendment
restates its Q1 revenue on the canonical + duplicate rows (8 restated).

Synthetic runs key every database row by a namespaced synthetic identity
(synthetic_cik / synthetic_entity_id) — never the real cohort CIKs — so
synthetic and live runs can never collide in the same database.
"""

from __future__ import annotations

import copy
import json
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import conninfo

from fel_providers.mocks import MockStorageProvider
from fel_workers import queue
from fel_workers.consumer import entity_id_for_cik, run_worker
from fel_workers.ingestion.discovery import JOB_KIND_SEC_DISCOVERY, JOB_KIND_SEC_FILING_FETCH
from fel_workers.ingestion.sec_client import normalize_cik
from harness import corpus_qa
from harness.corpus_qa import (
    ACCEPTANCE_DEFERRED_LIVE_REASON,
    DEFAULT_COHORT_PATH,
    RATE_UNAVAILABLE,
    HarnessError,
    collect_job_outcomes,
    ensure_disposable_reset_target,
    evaluate_acceptance,
    load_cohort,
    main,
    run_corpus_qa,
    run_failure_reasons,
    synthetic_cik,
    synthetic_entity_id,
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
EXPECTED_JOBS = 70  # 20 discovery + 50 fetch


def _cohort_tickers() -> list[str]:
    return [issuer["ticker"] for issuer in load_cohort(DEFAULT_COHORT_PATH).issuers]


def _synthetic_ciks() -> list[str]:
    return [synthetic_cik(ticker) for ticker in _cohort_tickers()]


# ---------------------------------------------------------------------------
# Deterministic synthetic corpus (no DB, no network).
# ---------------------------------------------------------------------------


def test_synthetic_client_is_deterministic_and_labeled() -> None:
    ciks = _synthetic_ciks()
    first, second = SyntheticCohortSecClient(ciks), SyntheticCohortSecClient(ciks)
    for index, cik in enumerate(ciks):
        assert first.submissions(cik) == second.submissions(cik)
        for filing in build_plan(cik, index):
            rendered = render_filing(filing)
            assert rendered == render_filing(filing), "same inputs, same bytes"
            assert b"SYNTHETIC" in rendered, "every synthetic document is labeled"
            assert cik.encode() in rendered


def test_synthetic_plan_matches_documented_expectations() -> None:
    ciks = _synthetic_ciks()
    assert len(ciks) == EXPECTED_ISSUERS
    plans = [build_plan(cik, index) for index, cik in enumerate(ciks)]
    total = sum(len(plan) for plan in plans)
    assert total == EXPECTED_DOCUMENTS
    accessions = [filing.accession for plan in plans for filing in plan]
    assert len(set(accessions)) == total, "accessions are globally unique"
    amendments = [f for plan in plans for f in plan if f.form == "10-Q/A"]
    assert len(amendments) == 4
    for amendment in amendments:
        assert amendment.revenue_offset != 0, "amendments must change the revenue"


def test_synthetic_identities_are_namespaced_and_disjoint_from_cohort() -> None:
    """Finding 3a: synthetic DB identities can never collide with the real
    cohort CIKs/entity ids (or with each other), and are deterministic."""
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    syn_ciks = set()
    for issuer in cohort.issuers:
        syn = synthetic_cik(issuer["ticker"])
        assert syn == synthetic_cik(issuer["ticker"]), "deterministic"
        assert syn.isdigit() and len(syn) == 12
        assert normalize_cik(syn) == syn, "already normalized (12 > 10 digits)"
        assert normalize_cik(syn) != normalize_cik(issuer["cik"])
        assert synthetic_entity_id(issuer["ticker"]) != entity_id_for_cik(issuer["cik"])
        syn_ciks.add(syn)
    assert len(syn_ciks) == len(cohort.issuers), "no synthetic collisions"


# ---------------------------------------------------------------------------
# End-to-end synthetic run through the real pipeline (DB-backed).
# ---------------------------------------------------------------------------


@pytest.fixture()
def synthetic_report(qa_database_url: str, tmp_path: pathlib.Path) -> dict[str, Any]:
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="test-synthetic",
    )
    assert result.failed is False, result.failure_reasons
    payload = json.loads(result.path.read_text())
    assert isinstance(payload, dict)
    return payload


def test_synthetic_run_records_expected_corpus_quality_metrics(
    synthetic_report: dict[str, Any],
) -> None:
    validate_report(synthetic_report)  # schema-valid by construction
    assert synthetic_report["mode"] == "synthetic"
    assert "SYNTHETIC" in str(synthetic_report["provenance_note"])
    issuers = synthetic_report["issuers"]
    totals = synthetic_report["totals"]
    assert len(issuers) == EXPECTED_ISSUERS
    assert totals["expected_documents"] == EXPECTED_DOCUMENTS
    assert totals["documents_ingested"] == EXPECTED_DOCUMENTS
    assert totals["documents_parsed"] == EXPECTED_PARSED
    assert totals["documents_quarantined"] == EXPECTED_QUARANTINED
    assert totals["facts_duplicate"] == EXPECTED_DUPLICATES
    assert totals["facts_restated"] == EXPECTED_RESTATED
    assert totals["quarantine_reason_distribution"] == EXPECTED_QUARANTINE_DISTRIBUTION
    assert totals["facts_total"] > 0


def test_synthetic_run_records_per_job_terminal_outcomes(
    synthetic_report: dict[str, Any],
) -> None:
    """Finding 2a: the report carries queryable per-job terminal outcomes,
    not just the consumer's completion count."""
    jobs = synthetic_report["pipeline"]["jobs"]
    assert jobs["discovery_expected"] == EXPECTED_ISSUERS
    assert jobs["fetch_expected"] == EXPECTED_DOCUMENTS
    assert jobs["terminal_counts"] == {"succeeded": EXPECTED_JOBS}
    assert jobs["pending"] == 0
    assert jobs["missing_fetch_jobs"] == []
    assert jobs["backlog_after_run"] == 0
    assert jobs["failures"] == []
    assert jobs["surplus_fetch_jobs"] == []
    assert jobs["stale_fetch_jobs"] == []
    assert synthetic_report["pipeline"]["jobs_completed"] == EXPECTED_JOBS


def test_synthetic_run_is_never_acceptance_grade(synthetic_report: dict[str, Any]) -> None:
    """Finding 4 (governance): a synthetic report never claims T0112
    acceptance; the live-run deferral is stated explicitly."""
    acceptance = synthetic_report["acceptance"]
    assert acceptance["accepted"] is False
    assert ACCEPTANCE_DEFERRED_LIVE_REASON in acceptance["reasons"]


def test_synthetic_run_provenance_uses_namespaced_identities(
    synthetic_report: dict[str, Any],
) -> None:
    """Finding 3a/3c: every issuer row is keyed by the synthetic entity id,
    never the real cohort entity id, and run provenance is recorded."""
    run = synthetic_report["run"]
    assert run["mode"] == "synthetic"
    assert run["identity_namespace"] == corpus_qa.SYNTHETIC_IDENTITY_NAMESPACE
    assert run["as_of"] == synthetic_report["cohort"]["as_of"]
    assert run["run_id"]
    assert run["expected_issuers"] == _cohort_tickers()
    for issuer in synthetic_report["issuers"]:
        assert issuer["entity_id"] == synthetic_entity_id(issuer["ticker"])
        assert issuer["entity_id"] != entity_id_for_cik(issuer["cik"])


def test_synthetic_run_span_hashes_all_verify(synthetic_report: dict[str, Any]) -> None:
    """Citation integrity: 100% of persisted span hashes re-verify against
    the canonical text the pipeline stored — per issuer and in total."""
    totals = synthetic_report["totals"]
    assert totals["spans_total"] > 0
    assert totals["spans_verified"] == totals["spans_total"]
    assert totals["span_hash_verification_rate"] == "1.000000"
    for issuer in synthetic_report["issuers"]:
        assert issuer["spans_verified"] == issuer["spans_total"]
        assert issuer["span_hash_verification_rate"] == "1.000000"


def test_synthetic_run_per_issuer_shape(synthetic_report: dict[str, Any]) -> None:
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    by_cik = {issuer["cik"]: issuer for issuer in synthetic_report["issuers"]}
    for index, member in enumerate(cohort.issuers):
        metrics = by_cik[member["cik"]]
        assert metrics["ticker"] == member["ticker"]
        expected_parsed = 2 + (1 if index % 5 == 0 else 0)
        expected_quarantined = (1 if index % 7 == 3 else 0) + (1 if index % 7 == 5 else 0)
        assert metrics["documents_parsed"] == expected_parsed, member
        assert metrics["documents_quarantined"] == expected_quarantined, member
        assert metrics["documents_ingested"] == expected_parsed + expected_quarantined
        assert metrics["expected_documents"] == expected_parsed + expected_quarantined
        assert metrics["facts_duplicate"] == expected_parsed
        assert metrics["facts_restated"] == (2 if index % 5 == 0 else 0), member
        assert metrics["facts_total"] > 0


def test_rerun_without_reset_is_refused_by_dedicated_db_gate(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding R2-1a/R2-4: the previously documented rerun path (same
    database, no --storage-dir) used to dedupe fetch jobs into the new
    run's accounting and then crash with a raw KeyError in span
    verification. The dedicated-DB gate now refuses it cleanly: exit 2
    BEFORE any enqueue or crash, and no report is written."""
    first = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="run-one",
    )
    assert first.failed is False
    with pytest.raises(HarnessError, match="dedicated database"):
        run_corpus_qa(
            mode="synthetic",
            database_url=qa_database_url,
            reports_dir=tmp_path,
            label="run-two",
        )
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "run-two-cli",
        ]
    )
    assert rc == 2
    assert not (tmp_path / "run-two.json").exists()
    assert not (tmp_path / "run-two-cli.json").exists()


def test_reset_rerun_reproduces_identical_metrics(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T0111c meets T0112 under the dedicated-DB ruling: replaying the
    cohort run is done on a RESET disposable database (the gate refuses a
    used one) and reproduces identical corpus metrics."""
    dbname = conninfo.conninfo_to_dict(qa_database_url).get("dbname")
    if not str(dbname or "").endswith("_test"):  # pragma: no cover — CI uses fel_test
        monkeypatch.setenv("FEL_HARNESS_ALLOW_RESET", "1")
    first_result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="run-one",
    )
    second_result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="run-two",
        reset=True,
    )
    assert first_result.failed is False and second_result.failed is False
    first = json.loads(first_result.path.read_text())
    second = json.loads(second_result.path.read_text())
    assert first["issuers"] == second["issuers"]
    assert first["totals"] == second["totals"]
    assert first["cohort"] == second["cohort"]
    assert first["run"]["run_id"] != second["run"]["run_id"]
    # Each pass starts from an empty queue, so both fully re-execute.
    assert second["pipeline"]["jobs_completed"] == EXPECTED_JOBS
    assert second["pipeline"]["jobs"]["terminal_counts"] == {"succeeded": EXPECTED_JOBS}


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
# Finding 1: the destructive reset fails closed.
# ---------------------------------------------------------------------------


def _seed_marker_job(database_url: str) -> str:
    marker = str(uuid.uuid4())
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("INSERT INTO jobs (id, kind, payload) VALUES (%s, 'marker', '{}')", (marker,))
    return marker


def _marker_job_exists(database_url: str, marker: str) -> bool:
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE id = %s", (marker,)).fetchone()
    return row is not None


def test_reset_never_falls_back_to_fel_database_url(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With only FEL_DATABASE_URL configured, --reset-corpus is refused
    (exit 2) before any connection — nothing is deleted."""
    marker = _seed_marker_job(qa_database_url)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("FEL_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reset-corpus",
            "--i-know-this-destroys-data",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "refused",
        ]
    )
    assert rc == 2
    assert not (tmp_path / "refused.json").exists()
    assert _marker_job_exists(qa_database_url, marker), "no delete may have run"


def test_reset_requires_explicit_destroy_confirmation(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _seed_marker_job(qa_database_url)
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reset-corpus",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "refused",
        ]
    )
    assert rc == 2
    assert _marker_job_exists(qa_database_url, marker), "no delete may have run"


def test_reset_refuses_non_test_database_name(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database not named *_test is refused before any connection (the
    URL below points nowhere; a connection attempt would fail differently)."""
    monkeypatch.delenv("FEL_HARNESS_ALLOW_RESET", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reset-corpus",
            "--i-know-this-destroys-data",
            "--database-url",
            "postgresql://fel@production.invalid:5432/fel_production",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "refused",
        ]
    )
    assert rc == 2
    assert not (tmp_path / "refused.json").exists()


def test_reset_disposability_override_is_explicit() -> None:
    url = "postgresql://fel@localhost/fel_scratch"
    with pytest.raises(HarnessError, match="_test"):
        ensure_disposable_reset_target(url, {})
    ensure_disposable_reset_target(url, {"FEL_HARNESS_ALLOW_RESET": "1"})
    ensure_disposable_reset_target("postgresql://fel@localhost/fel_test", {})


def test_reset_happy_path_on_disposable_test_database(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _seed_marker_job(qa_database_url)
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    dbname = conninfo.conninfo_to_dict(qa_database_url).get("dbname")
    if not str(dbname or "").endswith("_test"):  # pragma: no cover — CI uses fel_test
        monkeypatch.setenv("FEL_HARNESS_ALLOW_RESET", "1")
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reset-corpus",
            "--i-know-this-destroys-data",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "reset-ok",
        ]
    )
    assert rc == 0
    report = json.loads((tmp_path / "reset-ok.json").read_text())
    validate_report(report)
    assert report["totals"]["documents_ingested"] == EXPECTED_DOCUMENTS
    assert not _marker_job_exists(qa_database_url, marker), "reset emptied the queue"


# ---------------------------------------------------------------------------
# Finding 2: success is proven per job; empty denominators are unavailable.
# ---------------------------------------------------------------------------


def test_exhausted_iteration_budget_is_a_run_failure(
    qa_database_url: str, tmp_path: pathlib.Path
) -> None:
    """A run that returns with jobs still pending (iteration budget too
    small to drain the queue) fails: nonzero exit, non-acceptance report."""
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="undrained",
        max_iterations=3,
    )
    assert result.failed is True
    assert any("budget" in reason or "queued" in reason for reason in result.failure_reasons)
    report = result.report
    assert report["acceptance"]["accepted"] is False
    jobs = report["pipeline"]["jobs"]
    assert jobs["backlog_after_run"] > 0
    assert jobs["pending"] > 0 or jobs["missing_fetch_jobs"]


def test_exhausted_iteration_budget_exits_nonzero(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "undrained-cli",
            "--max-iterations",
            "3",
        ]
    )
    assert rc == 1
    assert (tmp_path / "undrained-cli.json").exists(), "the failed run still writes its report"


class _EmptySubmissionsClient:
    """SecClient stub: every issuer exists but has zero filings."""

    def submissions(self, cik: str) -> dict[str, object]:
        return {
            "cik": cik,
            "filings": {
                "recent": {
                    "accessionNumber": [],
                    "form": [],
                    "filingDate": [],
                    "primaryDocument": [],
                }
            },
        }

    def fetch_document(self, url: str) -> bytes:
        raise AssertionError("a zero-filing run must never fetch a document")


def test_zero_evidence_run_is_non_acceptance_with_unavailable_rates(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 2b/2d: a drained-but-empty run is not a run failure, but it
    is never acceptance-grade, and no rate fails open to '1'."""
    monkeypatch.setattr(
        corpus_qa, "SyntheticCohortSecClient", lambda ciks: _EmptySubmissionsClient()
    )
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="zero-evidence",
    )
    assert result.failed is False, result.failure_reasons
    report = result.report
    assert report["acceptance"]["accepted"] is False
    reasons = " | ".join(report["acceptance"]["reasons"])
    assert "zero-evidence" in reasons
    assert "without a successfully parsed document" in reasons
    assert report["totals"]["spans_total"] == 0
    assert report["totals"]["span_hash_verification_rate"] == RATE_UNAVAILABLE
    for issuer in report["issuers"]:
        assert issuer["span_hash_verification_rate"] == RATE_UNAVAILABLE


class _FailingFetchClient:
    """SecClient stub: discovery works, every document fetch fails."""

    def __init__(self, inner: SyntheticCohortSecClient) -> None:
        self._inner = inner

    def submissions(self, cik: str) -> dict[str, object]:
        return self._inner.submissions(cik)

    def fetch_document(self, url: str) -> bytes:
        raise RuntimeError("synthetic outage: fetch refused")


def test_failed_fetch_jobs_are_a_run_failure_with_recorded_errors(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 2a/2c: parked-failed jobs surface as a run failure with
    their terminal status and error captured in the report."""
    cohort_path = tmp_path / "one-issuer-cohort.json"
    cohort_path.write_text(
        json.dumps(
            {
                "as_of": "2026-07-14",
                "issuers": [{"ticker": "SYN1", "cik": "0000000001", "name": "Synthetic One"}],
            }
        )
    )
    monkeypatch.setattr(
        corpus_qa,
        "SyntheticCohortSecClient",
        lambda ciks: _FailingFetchClient(SyntheticCohortSecClient(ciks)),
    )
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="fetch-outage",
        cohort_path=cohort_path,
        max_iterations=200,
    )
    assert result.failed is True
    report = result.report
    assert report["acceptance"]["accepted"] is False
    jobs = report["pipeline"]["jobs"]
    assert jobs["terminal_counts"].get("failed", 0) == 3  # 10-K, 10-Q, 10-Q/A
    failures = jobs["failures"]
    assert len(failures) == 3
    for failure in failures:
        assert failure["status"] == "failed"
        assert "synthetic outage" in str(failure["error"])
        assert failure["accession"]


# ---------------------------------------------------------------------------
# Round-2 finding 1: the dedicated-database gate (both modes) and the
# created_at staleness belt-and-braces.
# ---------------------------------------------------------------------------


def test_preexisting_jobs_are_refused_fail_closed(
    qa_database_url: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Finding R2-1a: ANY pre-existing job in the queue (here: an unrelated
    marker job) means the database is not dedicated — exit 2 before any
    enqueue, nothing deleted, no report written."""
    marker = _seed_marker_job(qa_database_url)
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "not-dedicated",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "dedicated database" in err
    assert "1 pre-existing jobs" in err
    assert not (tmp_path / "not-dedicated.json").exists()
    assert _marker_job_exists(qa_database_url, marker), "the gate must not delete anything"


def test_preexisting_expected_fetch_key_is_refused_fail_closed(
    qa_database_url: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Finding R2-1a: a pre-existing fetch job carrying one of THIS run's
    expected idempotency keys (a prior harness run or a production worker)
    would silently satisfy dedupe and be mis-attributed to this run — the
    gate refuses it. Since round 3 the gate is split: the pre-seeded job
    is caught by the empty-queue half BEFORE any submissions snapshot
    (see test_live_gate_refusal_burns_zero_sec_requests); the key half
    remains as a post-snapshot race guard (see
    test_expected_key_race_guard_is_the_gates_second_half)."""
    accession = build_plan(_synthetic_ciks()[0], 0)[0].accession
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        queue.enqueue(
            conn,
            kind=JOB_KIND_SEC_FILING_FETCH,
            payload={"accession": accession},
            queue="ingestion",
            idempotency_key=f"sec-fetch|{accession}",
        )
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "stale-key",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "dedicated database" in err
    assert "1 pre-existing jobs" in err
    assert not (tmp_path / "stale-key.json").exists()
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        row = conn.execute("SELECT count(*) FROM jobs").fetchone()
    assert row is not None and row[0] == 1, "the gate must neither enqueue nor delete"


def test_stale_expected_fetch_jobs_are_a_run_failure(
    qa_database_url: str, tmp_path: pathlib.Path
) -> None:
    """Finding R2-1b (belt-and-braces): an expected fetch job whose
    created_at predates the run start is accounted as a stale corpus row
    and fails the run — even if the pre-run gate were somehow bypassed."""
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="stale-probe",
    )
    assert result.failed is False
    accessions = [
        filing.accession
        for index, cik in enumerate(_synthetic_ciks())
        for filing in build_plan(cik, index)
    ]
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        jobs = collect_job_outcomes(
            conn,
            discovery_job_ids=[],
            expected_accessions=accessions,
            # Pretend the run started in the future: every fetch job in the
            # queue now predates it, i.e. is a stale historical row.
            run_started_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert set(jobs.stale_accessions) == set(accessions)
    assert jobs.as_report_field()["stale_fetch_jobs"] == sorted(accessions)
    reasons = run_failure_reasons(jobs)
    assert any("stale corpus rows" in reason for reason in reasons)


# ---------------------------------------------------------------------------
# Round-2 finding 2: the expected-set snapshot race — surplus fetch jobs
# are reconciled, reported, and fail the run when not succeeded.
# ---------------------------------------------------------------------------


def _one_issuer_cohort(tmp_path: pathlib.Path) -> pathlib.Path:
    cohort_path = tmp_path / "one-issuer-cohort.json"
    cohort_path.write_text(
        json.dumps(
            {
                "as_of": "2026-07-14",
                "issuers": [{"ticker": "SYN1", "cik": "0000000001", "name": "Synthetic One"}],
            }
        )
    )
    return cohort_path


class _LateFilingClient:
    """SecClient stub reproducing the live snapshot race: the FIRST
    submissions() call per CIK (the harness's expected-set snapshot) omits
    the newest filing; the discovery job's own later call sees it."""

    def __init__(self, inner: SyntheticCohortSecClient, *, late_fetch_fails: bool) -> None:
        self._inner = inner
        self._snapshotted: set[str] = set()
        self.late_documents: set[str] = set()
        self.late_accessions: set[str] = set()
        self._late_fetch_fails = late_fetch_fails

    def submissions(self, cik: str) -> dict[str, object]:
        payload = copy.deepcopy(self._inner.submissions(cik))
        recent = payload["filings"]["recent"]  # type: ignore[index]
        if cik not in self._snapshotted:
            self._snapshotted.add(cik)
            self.late_documents.add(str(recent["primaryDocument"][-1]))
            self.late_accessions.add(str(recent["accessionNumber"][-1]))
            for field in ("accessionNumber", "form", "filingDate", "primaryDocument"):
                recent[field] = recent[field][:-1]
        return payload

    def fetch_document(self, url: str) -> bytes:
        name = url.rsplit("/", 1)[-1]
        if self._late_fetch_fails and name in self.late_documents:
            raise RuntimeError("synthetic outage: late-arriving filing fetch refused")
        return self._inner.fetch_document(url)


def test_surplus_fetch_job_failure_is_a_run_failure(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding R2-2: a filing that appears between the harness snapshot and
    the discovery job's own listing yields a fetch job OUTSIDE the expected
    set. It must not be invisible: it is reconciled as surplus, and its
    failure fails the run."""
    clients: list[_LateFilingClient] = []

    def _factory(ciks: list[str]) -> _LateFilingClient:
        client = _LateFilingClient(SyntheticCohortSecClient(ciks), late_fetch_fails=True)
        clients.append(client)
        return client

    monkeypatch.setattr(corpus_qa, "SyntheticCohortSecClient", _factory)
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="surplus-outage",
        cohort_path=_one_issuer_cohort(tmp_path),
        max_iterations=200,
    )
    assert result.failed is True
    assert any("surplus" in reason for reason in result.failure_reasons)
    jobs = result.report["pipeline"]["jobs"]
    # The expected jobs (1 discovery + 2 snapshot fetches) all succeeded —
    # without surplus reconciliation this failure would be invisible.
    assert jobs["failures"] == []
    assert jobs["terminal_counts"] == {"succeeded": 3}
    (surplus,) = jobs["surplus_fetch_jobs"]
    assert surplus["status"] == "failed"
    assert surplus["accession"] in clients[0].late_accessions
    assert "synthetic outage" in str(surplus["error"])
    assert result.report["acceptance"]["accepted"] is False


def test_succeeded_surplus_fetch_job_is_recorded_but_not_a_failure(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding R2-2: a surplus fetch job that SUCCEEDS is not a run
    failure, but it is recorded in the report and stays out of the
    expected-set metrics."""
    monkeypatch.setattr(
        corpus_qa,
        "SyntheticCohortSecClient",
        lambda ciks: _LateFilingClient(SyntheticCohortSecClient(ciks), late_fetch_fails=False),
    )
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="surplus-ok",
        cohort_path=_one_issuer_cohort(tmp_path),
    )
    assert result.failed is False, result.failure_reasons
    report = result.report
    (surplus,) = report["pipeline"]["jobs"]["surplus_fetch_jobs"]
    assert surplus["status"] == "succeeded"
    # SYN1 (index 0) plans 10-K + 10-Q + 10-Q/A; the snapshot saw only the
    # first two, and the late 10-Q/A stays out of the scoped metrics.
    issuer = report["issuers"][0]
    assert issuer["expected_documents"] == 2
    assert issuer["documents_ingested"] == 2
    assert report["totals"]["documents_ingested"] == 2


# ---------------------------------------------------------------------------
# Round-2 finding 4: span verification never leaks a raw KeyError.
# ---------------------------------------------------------------------------


def test_verify_spans_missing_blob_raises_harness_error(
    qa_database_url: str, tmp_path: pathlib.Path
) -> None:
    """Finding R2-4 (defensive half; the gate covers the CLI path): corpus
    rows whose canonical-text blobs are absent from this run's storage
    raise a diagnosable HarnessError, never a raw KeyError."""
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="blob-probe",
        storage_dir=tmp_path / "blobs",
    )
    assert result.failed is False
    ticker = _cohort_tickers()[0]
    accessions = [filing.accession for filing in build_plan(synthetic_cik(ticker), 0)]
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        with pytest.raises(HarnessError, match="absent from this run's storage"):
            corpus_qa._verify_spans(
                conn, MockStorageProvider(), synthetic_entity_id(ticker), accessions
            )


# ---------------------------------------------------------------------------
# Round-2 finding 5: the exit-code contract never leaks raw tracebacks.
# ---------------------------------------------------------------------------


def _assert_one_line_config_error(capsys: pytest.CaptureFixture[str]) -> str:
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected a one-line message, got: {err!r}"
    assert lines[0].startswith("corpus-qa:")
    assert "Traceback" not in err
    return lines[0]


def test_unreachable_database_exits_2_with_one_line_message(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding R2-5: a connection/DSN error is a CONFIG failure (exit 2,
    one line) — never a raw psycopg.OperationalError traceback."""
    rc = main(
        [
            "--mode",
            "synthetic",
            "--database-url",
            "postgresql://fel@127.0.0.1:9/fel_test",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "no-database",
        ]
    )
    assert rc == 2
    message = _assert_one_line_config_error(capsys)
    assert "cannot connect" in message
    assert not (tmp_path / "no-database.json").exists()


def test_missing_cohort_file_exits_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "--mode",
            "synthetic",
            "--database-url",
            _UNROUTABLE_DB,
            "--cohort",
            str(tmp_path / "does-not-exist.json"),
            "--reports-dir",
            str(tmp_path),
            "--label",
            "no-cohort",
        ]
    )
    assert rc == 2
    message = _assert_one_line_config_error(capsys)
    assert "unreadable" in message


def test_malformed_cohort_json_exits_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad-cohort.json"
    bad.write_text("{ this is not json")
    rc = main(
        [
            "--mode",
            "synthetic",
            "--database-url",
            _UNROUTABLE_DB,
            "--cohort",
            str(bad),
            "--reports-dir",
            str(tmp_path),
            "--label",
            "bad-cohort",
        ]
    )
    assert rc == 2
    message = _assert_one_line_config_error(capsys)
    assert "not valid JSON" in message


# ---------------------------------------------------------------------------
# Round-3 finding 1: gate ordering — the empty-queue half of the
# dedicated-DB gate refuses BEFORE any SEC request (zero fair-access
# budget burned); the expected-key half stays as a post-snapshot race
# guard.
# ---------------------------------------------------------------------------


def test_live_gate_refusal_burns_zero_sec_requests(
    qa_database_url: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Round-3 finding 1: a live-shaped run against a database with one
    pre-existing job is refused (exit 2) by the empty-queue gate BEFORE
    the expected-set snapshot — ZERO SEC requests are recorded."""
    _seed_marker_job(qa_database_url)
    requests: list[str] = []

    class _CountingLiveClient:
        def __init__(self, *, user_agent: str) -> None:
            self.user_agent = user_agent

        def submissions(self, cik: str) -> dict[str, object]:
            requests.append(f"submissions|{cik}")
            raise AssertionError("a refused run must never reach SEC")

        def fetch_document(self, url: str) -> bytes:
            requests.append(f"fetch|{url}")
            raise AssertionError("a refused run must never reach SEC")

    monkeypatch.setattr("fel_workers.ingestion.sec_client.LiveSecClient", _CountingLiveClient)
    monkeypatch.setenv("FEL_SEC_USER_AGENT", "fel corpus-qa (ops@example.com)")
    rc = main(
        [
            "--mode",
            "live",
            "--database-url",
            qa_database_url,
            "--storage-dir",
            str(tmp_path / "blobs"),
            "--reports-dir",
            str(tmp_path),
            "--label",
            "live-not-dedicated",
        ]
    )
    assert rc == 2
    assert requests == [], "the refusal must record ZERO SEC requests"
    err = capsys.readouterr().err
    assert "dedicated database" in err
    assert "1 pre-existing jobs" in err
    assert not (tmp_path / "live-not-dedicated.json").exists()


def test_expected_key_race_guard_is_the_gates_second_half(qa_database_url: str) -> None:
    """Round-3 finding 1: the expected-key check remains after the
    snapshot as a race guard — a writer that claimed one of this run's
    expected fetch keys between the empty-queue gate and enqueue is still
    refused fail-closed."""
    accession = build_plan(_synthetic_ciks()[0], 0)[0].accession
    key = f"sec-fetch|{accession}"
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        corpus_qa.ensure_expected_keys_unclaimed(conn, [key])  # empty queue: passes
        queue.enqueue(
            conn,
            kind=JOB_KIND_SEC_FILING_FETCH,
            payload={"accession": accession},
            queue="ingestion",
            idempotency_key=key,
        )
        with pytest.raises(HarnessError, match="pre-existing fetch keys"):
            corpus_qa.ensure_expected_keys_unclaimed(conn, [key])


# ---------------------------------------------------------------------------
# Round-3 findings 2+3: phase-aware failure semantics — ANY failure after
# work starts (the first enqueue) exits 1 with a best-effort failure
# report, never an exit-2 config refusal.
# ---------------------------------------------------------------------------


def test_midrun_missing_blob_is_run_failure_not_refusal(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-3 finding 2 (reproduced scenario): run once, DELETE FROM
    jobs, rerun with fresh storage. The rerun passes the gate (empty
    queue), re-enqueues, then span verification raises HarnessError
    MID-RUN because the corpus rows reference the first run's blobs. That
    is a RUN FAILURE: exit 1 with a written non-acceptance failure report
    naming the missing-blob reason — not exit 2.

    The dedicated-DB gate now also refuses leftover CORPUS rows (see
    test_preexisting_documents_are_refused_fail_closed), which closes this
    scenario's front door; the gate is bypassed here deliberately to keep
    the mid-run phase semantics (defense-in-depth) pinned."""
    monkeypatch.setattr("harness.corpus_qa.ensure_dedicated_queue", lambda conn: None)
    first = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="first-pass",
    )
    assert first.failed is False
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM jobs")
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "rerun-fresh-storage",
        ]
    )
    assert rc == 1
    report = json.loads((tmp_path / "rerun-fresh-storage.json").read_text())
    assert report["schema"] == corpus_qa.FAILURE_SCHEMA
    assert report["acceptance"]["accepted"] is False
    reasons = " | ".join(report["acceptance"]["reasons"])
    assert "absent from this run's storage" in reasons
    assert report["run_failure"]["failure_reason"] in report["acceptance"]["reasons"]
    # A failure report can never masquerade as a metrics report.
    with pytest.raises(HarnessError, match="unexpected schema"):
        validate_report(report)


def test_connection_lost_after_enqueue_is_run_failure_with_report(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-3 finding 3: an OperationalError AFTER work starts (the
    harness's backend terminated mid-run) is a RUN FAILURE — exit 1 with
    a best-effort failure report written locally (the report is
    filesystem JSON; a dead connection cannot stop it) — never exit 2."""

    def _terminating_worker(
        conn: psycopg.Connection[Any],
        storage: object,
        sec: object,
        *,
        queue_name: str,
        max_iterations: int,
    ) -> int:
        with psycopg.connect(qa_database_url, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))
        return 0

    monkeypatch.setattr(corpus_qa, "run_worker", _terminating_worker)
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "conn-lost",
        ]
    )
    assert rc == 1
    report = json.loads((tmp_path / "conn-lost.json").read_text())
    assert report["schema"] == corpus_qa.FAILURE_SCHEMA
    assert report["acceptance"]["accepted"] is False
    assert "run failed after work started" in report["acceptance"]["reasons"][0]
    assert report["run_failure"]["failure_reason"] == report["acceptance"]["reasons"][0]
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        row = conn.execute("SELECT count(*) FROM jobs").fetchone()
    assert row is not None and row[0] > 0, "work had started: discovery jobs were enqueued"


# ---------------------------------------------------------------------------
# Finding 3: synthetic/live separation and per-run metric scoping.
# ---------------------------------------------------------------------------


def test_synthetic_then_live_shaped_run_share_nothing(
    qa_database_url: str, tmp_path: pathlib.Path
) -> None:
    """A synthetic run followed by a live-shaped run (real-CIK keys) in the
    SAME database: no discovery/fetch idempotency collision, disjoint
    entity ids, and the live-shaped rows never enter synthetic metrics."""
    synthetic_result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="before-live",
    )
    assert synthetic_result.failed is False
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    real_ciks = [normalize_cik(issuer["cik"]) for issuer in cohort.issuers]
    live_shaped_sec = SyntheticCohortSecClient(real_ciks)
    storage = MockStorageProvider()
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        for cik in real_ciks:
            queue.enqueue(
                conn,
                kind=JOB_KIND_SEC_DISCOVERY,
                payload={"cik": cik},
                queue="ingestion",
                idempotency_key=f"corpus-qa|live-shaped|discovery|{cik}",
            )
        run_worker(conn, storage, live_shaped_sec, queue_name="ingestion", max_iterations=10_000)
        fetch_jobs = conn.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'sec_filing_fetch'"
        ).fetchone()
        entity_rows = conn.execute("SELECT DISTINCT entity_id::text FROM documents").fetchall()
    # No fetch-job dedupe collision: both runs enqueued their full plans.
    assert fetch_jobs is not None and fetch_jobs[0] == 2 * EXPECTED_DOCUMENTS
    synthetic_ids = {synthetic_entity_id(issuer["ticker"]) for issuer in cohort.issuers}
    live_ids = {entity_id_for_cik(cik) for cik in real_ciks}
    assert synthetic_ids.isdisjoint(live_ids)
    assert {row[0] for row in entity_rows} == synthetic_ids | live_ids


def test_report_counts_only_this_runs_rows(
    qa_database_url: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3b: metrics aggregate over exactly this run's accession set —
    pre-existing rows under the same entity are excluded.

    The dedicated-DB gate would now refuse this dirty database outright;
    it is bypassed here deliberately so the run-scoped metric aggregation
    (defense-in-depth behind the gate) stays pinned."""
    monkeypatch.setattr("harness.corpus_qa.ensure_dedicated_queue", lambda conn: None)
    cohort = load_cohort(DEFAULT_COHORT_PATH)
    stray_entity = synthetic_entity_id(cohort.issuers[0]["ticker"])
    with psycopg.connect(qa_database_url, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO documents
                (id, entity_id, accession, source_url, content_hash, storage_key, published_at)
            VALUES (%s, %s, %s, 'https://synthetic.invalid/stray',
                    'sha256:' || repeat('0', 64), 'raw/stray', now())
            """,
            (str(uuid.uuid4()), stray_entity, "stray-prior-run-0001"),
        )
    result = run_corpus_qa(
        mode="synthetic",
        database_url=qa_database_url,
        reports_dir=tmp_path,
        label="scoped",
    )
    assert result.failed is False
    report = result.report
    issuer0 = report["issuers"][0]
    assert issuer0["entity_id"] == stray_entity
    # Issuer 0 (index 0) plans 10-K + 10-Q + 10-Q/A = 3; the stray row is
    # not in this run's accession set and must not be counted.
    assert issuer0["expected_documents"] == 3
    assert issuer0["documents_ingested"] == 3
    assert report["totals"]["documents_ingested"] == EXPECTED_DOCUMENTS


# ---------------------------------------------------------------------------
# Finding 5: live mode requires an explicit SEC identity, before network.
# ---------------------------------------------------------------------------

_UNROUTABLE_DB = "postgresql://fel@sec-identity.invalid:1/fel_test"


@pytest.mark.parametrize("user_agent", [None, "", "   ", "missing contact marker"])
def test_live_mode_requires_sec_user_agent_before_any_network(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, user_agent: str | None
) -> None:
    """Absent/blank/malformed FEL_SEC_USER_AGENT fails with HarnessError
    BEFORE any network or database access (the URL points nowhere: reaching
    it would raise OperationalError, not HarnessError)."""
    if user_agent is None:
        monkeypatch.delenv("FEL_SEC_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("FEL_SEC_USER_AGENT", user_agent)
    with pytest.raises(HarnessError, match="FEL_SEC_USER_AGENT"):
        run_corpus_qa(
            mode="live",
            database_url=_UNROUTABLE_DB,
            reports_dir=tmp_path,
            label="live-refused",
            storage_dir=tmp_path / "blobs",
        )


def test_live_mode_missing_sec_user_agent_exits_2(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FEL_SEC_USER_AGENT", raising=False)
    rc = main(
        [
            "--mode",
            "live",
            "--database-url",
            _UNROUTABLE_DB,
            "--storage-dir",
            str(tmp_path / "blobs"),
            "--reports-dir",
            str(tmp_path),
            "--label",
            "live-refused",
        ]
    )
    assert rc == 2


class _SentinelStop(Exception):
    pass


def test_live_mode_passes_configured_user_agent_to_live_client(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    class _RecordingClient:
        def __init__(self, *, user_agent: str) -> None:
            captured["user_agent"] = user_agent
            raise _SentinelStop

    monkeypatch.setenv("FEL_SEC_USER_AGENT", "fel corpus-qa (ops@example.com)")
    monkeypatch.setattr("fel_workers.ingestion.sec_client.LiveSecClient", _RecordingClient)
    with pytest.raises(_SentinelStop):
        run_corpus_qa(
            mode="live",
            database_url=_UNROUTABLE_DB,
            reports_dir=tmp_path,
            label="live-ua",
            storage_dir=tmp_path / "blobs",
        )
    assert captured["user_agent"] == "fel corpus-qa (ops@example.com)"


# ---------------------------------------------------------------------------
# Report schema validation + the committed synthetic artifact.
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


def _committed_synthetic_report() -> dict[str, Any]:
    committed = sorted(REPORTS_DIR.glob("*-synthetic-*.json"))
    assert committed, f"no committed synthetic corpus-qa report under {REPORTS_DIR}"
    report = json.loads(committed[-1].read_text())
    assert isinstance(report, dict)
    return report


def test_validate_report_rejects_mixed_or_ambiguous_provenance() -> None:
    """Finding 3c: a report whose identities or mode markers disagree is
    rejected — synthetic rows can never masquerade as live and vice versa."""
    base = _committed_synthetic_report()
    validate_report(base)

    cohort_keyed = copy.deepcopy(base)
    cohort_keyed["issuers"][0]["entity_id"] = entity_id_for_cik(cohort_keyed["issuers"][0]["cik"])
    with pytest.raises(HarnessError, match="provenance"):
        validate_report(cohort_keyed)

    mode_mismatch = copy.deepcopy(base)
    mode_mismatch["run"]["mode"] = "live"
    with pytest.raises(HarnessError, match="[Mm]ixed provenance"):
        validate_report(mode_mismatch)

    accepted_synthetic = copy.deepcopy(base)
    accepted_synthetic["acceptance"] = {"accepted": True, "reasons": []}
    with pytest.raises(HarnessError, match="acceptance"):
        validate_report(accepted_synthetic)


def test_validate_report_rejects_fail_open_rates() -> None:
    base = _committed_synthetic_report()
    tampered = copy.deepcopy(base)
    for issuer in tampered["issuers"]:
        issuer["spans_total"] = 0
        issuer["spans_verified"] = 0
    tampered["totals"]["spans_total"] = 0
    tampered["totals"]["spans_verified"] = 0
    tampered["totals"]["span_hash_verification_rate"] = "1"
    with pytest.raises(HarnessError, match="unavailable"):
        validate_report(tampered)


def test_committed_synthetic_report_is_schema_valid_and_labeled() -> None:
    """The committed synthetic report must validate, must be unambiguously
    labeled synthetic, and must NOT claim T0112 acceptance (the acceptance
    artifact is the deferred live run)."""
    committed = sorted(REPORTS_DIR.glob("*-synthetic-*.json"))
    assert committed, f"no committed synthetic corpus-qa report under {REPORTS_DIR}"
    for path in committed:
        report = json.loads(path.read_text())
        validate_report(report)
        assert report["mode"] == "synthetic"
        assert "SYNTHETIC" in report["provenance_note"]
        assert report["acceptance"]["accepted"] is False
        assert ACCEPTANCE_DEFERRED_LIVE_REASON in report["acceptance"]["reasons"]
        assert report["cohort"]["issuer_count"] == EXPECTED_ISSUERS
        assert report["totals"]["span_hash_verification_rate"] == "1.000000"
        # The committed artifact pins the exact cohort file it measured.
        cohort = load_cohort(DEFAULT_COHORT_PATH)
        assert report["cohort"]["sha256"] == cohort.sha256


def test_partial_span_hash_rate_blocks_acceptance() -> None:
    """Re-review nit (Important): a live run with any span-hash mismatch
    must not be acceptance-grade — the rate must be exactly 1.000000."""
    rows = [{"ticker": "X", "documents_parsed": 1}]
    perfect = evaluate_acceptance(
        "live", rows, {"spans_total": 10, "span_hash_verification_rate": "1.000000"}, []
    )
    partial = evaluate_acceptance(
        "live", rows, {"spans_total": 10, "span_hash_verification_rate": "0.998252"}, []
    )
    assert perfect["accepted"] is True
    assert partial["accepted"] is False
    assert any("1.000000" in r for r in partial["reasons"])


def test_preexisting_documents_are_refused_fail_closed(
    qa_database_url: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Re-review follow-up: a leftover CORPUS row (empty queue) also marks
    the database non-dedicated — exit 2 before any enqueue."""
    import uuid as _uuid

    import psycopg as _psycopg

    with _psycopg.connect(qa_database_url) as conn:
        conn.execute(
            "INSERT INTO documents (id, entity_id, accession, source_url,"
            " content_hash, storage_key, published_at)"
            " VALUES (%s, %s, 'MARKER-DOC-1', 'https://example.invalid/m',"
            " 'sha256:" + "0" * 64 + "', 'raw/sha256/marker', now())",
            (str(_uuid.uuid4()), str(_uuid.uuid4())),
        )
    monkeypatch.setenv("TEST_DATABASE_URL", qa_database_url)
    rc = main(
        [
            "--mode",
            "synthetic",
            "--reports-dir",
            str(tmp_path),
            "--label",
            "leftover-corpus",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "pre-existing" in err and "documents" in err
    assert not list(tmp_path.glob("*.json"))
