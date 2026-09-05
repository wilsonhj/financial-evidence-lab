"""Tests for the executable retrieval release gate (issue #201).

Two tiers: a pure unit test of report assembly + exit-code logic (no DB), and
a Postgres-gated end-to-end test that runs the CLI against a live database
twice and checks the graded section is byte-identical and matches the
committed golden. Skips cleanly when TEST_DATABASE_URL is unset, same pattern
as the rest of the suite (see ``evals/tests/conftest.py``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from fel_retrieval_evals.metrics import QuestionOutcome
from harness import retrieval_gate

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "evals" / "reports" / "retrieval-gate" / "2026-09-01-synthetic-seed.json"

# Keys inside a report that are allowed to vary run-to-run; everything else is
# the "graded section" the determinism contract covers.
_VOLATILE_META_KEYS = {"generated_at", "database", "index_reused"}


def _graded(report: dict) -> dict:
    meta = {k: v for k, v in report["meta"].items() if k not in _VOLATILE_META_KEYS}
    return {
        "gate": report["gate"],
        "not_evaluable": report["not_evaluable"],
        "questions": report["questions"],
        "per_question": report["per_question"],
        "meta": meta,
    }


# --- Unit: report assembly + exit-code logic (no DB) -----------------------


def test_assemble_report_all_computable_gates_pass() -> None:
    outcomes = [QuestionOutcome(recall_at_10=Decimal(1), temporal_ok=True) for _ in range(5)]
    per_question = [{"id": f"Q-{i}"} for i in range(5)]
    report = retrieval_gate.assemble_report(
        outcomes,
        per_question=per_question,
        excluded=[],
        total_questions=5,
        meta={"generated_at": "2026-01-01T00:00:00+00:00"},
    )
    assert report["schema_version"] == "retrieval-gate-report/v1"
    assert report["gate"]["passed"] is True
    names = {r["name"] for r in report["gate"]["results"]}
    assert names == {"recall_at_10", "temporal_validity"}
    assert set(report["not_evaluable"]) == {
        "numeric_accuracy",
        "entailment_precision",
        "citation_completeness",
    }
    for entry in report["not_evaluable"].values():
        assert entry["support"] == 0
    assert report["questions"] == {"total": 5, "evaluated": 5, "excluded": []}
    assert retrieval_gate.exit_code(report) == 0


def test_assemble_report_recall_failure_fails_the_gate_only() -> None:
    outcomes = [
        QuestionOutcome(recall_at_10=Decimal("0.1"), temporal_ok=True),
        QuestionOutcome(recall_at_10=Decimal("0.2"), temporal_ok=True),
    ]
    report = retrieval_gate.assemble_report(
        outcomes, per_question=[], excluded=[], total_questions=2, meta={}
    )
    results = {r["name"]: r for r in report["gate"]["results"]}
    assert results["recall_at_10"]["passed"] is False
    assert results["temporal_validity"]["passed"] is True
    assert report["gate"]["passed"] is False
    assert retrieval_gate.exit_code(report) == 1
    # not_evaluable metrics never leak into the pass/fail decision.
    assert "numeric_accuracy" not in results


def test_assemble_report_empty_outcomes_fails_closed_not_vacuous() -> None:
    """No outcomes at all -> zero support -> the gate must not vacuously pass."""
    report = retrieval_gate.assemble_report(
        [], per_question=[], excluded=[], total_questions=0, meta={}
    )
    results = {r["name"]: r for r in report["gate"]["results"]}
    assert results["recall_at_10"]["passed"] is False
    assert results["temporal_validity"]["passed"] is False
    assert retrieval_gate.exit_code(report) == 1


def test_reranker_trigger_reported_report_only() -> None:
    outcomes = [QuestionOutcome(recall_at_10=Decimal("0.5"), temporal_ok=True)]
    report = retrieval_gate.assemble_report(
        outcomes, per_question=[], excluded=[], total_questions=1, meta={}
    )
    assert report["gate"]["reranker"]["triggered"] is True
    outcomes_ok = [QuestionOutcome(recall_at_10=Decimal("0.95"), temporal_ok=True)]
    report_ok = retrieval_gate.assemble_report(
        outcomes_ok, per_question=[], excluded=[], total_questions=1, meta={}
    )
    assert report_ok["gate"]["reranker"]["triggered"] is False


def test_report_json_is_sorted_and_stable() -> None:
    outcomes = [QuestionOutcome(recall_at_10=Decimal(1), temporal_ok=True)]
    report = retrieval_gate.assemble_report(
        outcomes,
        per_question=[{"id": "Q-1"}],
        excluded=[],
        total_questions=1,
        meta={"generated_at": "x"},
    )
    first = json.dumps(report, sort_keys=True)
    second = json.dumps(
        retrieval_gate.assemble_report(
            outcomes,
            per_question=[{"id": "Q-1"}],
            excluded=[],
            total_questions=1,
            meta={"generated_at": "x"},
        ),
        sort_keys=True,
    )
    assert first == second


def test_live_provider_is_refused_before_any_work(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    code = retrieval_gate.main(["--provider", "live", "--out", str(out)])
    assert code == 2
    assert not out.exists()


def test_main_requires_a_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    out = tmp_path / "report.json"
    code = retrieval_gate.main(["--out", str(out), "--database-url", ""])
    assert code == 2
    assert not out.exists()


# --- Postgres-gated: end-to-end CLI determinism + golden -------------------


@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not configured")
def test_cli_end_to_end_is_deterministic_and_matches_golden(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    out1 = tmp_path / "run1.json"
    out2 = tmp_path / "run2.json"
    pythonpath = os.pathsep.join(
        [
            str(REPO_ROOT / "evals"),
            str(REPO_ROOT / "packages" / "retrieval"),
            str(REPO_ROOT / "packages" / "retrieval-evals"),
            str(REPO_ROOT / "packages" / "providers"),
        ]
    )
    env = {
        **os.environ,
        "TEST_DATABASE_URL": TEST_DATABASE_URL,
        "PYTHONPATH": pythonpath,
    }

    for out in (out1, out2):
        subprocess.run(
            [sys.executable, "-m", "harness.retrieval_gate", "--out", str(out)],
            cwd=REPO_ROOT,
            env=env,
            check=False,  # the gate may legitimately exit 1 (a failed gate)
        )
        assert out.exists(), f"{out} was not written"

    report1 = json.loads(out1.read_text())
    report2 = json.loads(out2.read_text())
    assert _graded(report1) == _graded(report2)

    golden = json.loads(GOLDEN.read_text())
    assert _graded(report1) == _graded(golden)
