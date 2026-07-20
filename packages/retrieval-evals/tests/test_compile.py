"""Unit tests for the benchmark manifest compiler (M2-023 / T0214a)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fel_retrieval_evals.compile import CompilationError, compile_manifest, load_seed
from fel_retrieval_evals.corpus import JsonCorpus

ACC = "0001628280-26-038798"
SECTION = "Financial Highlights - Revenue"
QUOTE = "Total revenue was $687.6 million for the first quarter of fiscal 2027."


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "BM-0001",
        "category": "exact_fact_lookup",
        "issuer": {"ticker": "MDB", "cik": "0001441816"},
        "question": "What was revenue?",
        "as_of": "2026-05-28T00:00:00Z",
        "expected_answer": {
            "kind": "numeric",
            "value": "687.6",
            "unit": "USD",
            "scale": "millions",
            "period": "Q1 FY2027",
        },
        "evidence": [{"accession": ACC, "form": "8-K", "section": SECTION, "quote": QUOTE}],
        "documents_reviewed": [ACC],
        "answerable": True,
        "difficulty": "easy",
        "author_notes": "",
        "adjudication": {"status": "draft", "reviewers": []},
    }
    record.update(overrides)
    return record


def _corpus(*, acceptance: str = "2026-05-27T20:05:00Z", spans: int = 1) -> JsonCorpus:
    span_list = [
        {"section": SECTION, "span_id": f"span-{i}", "text": f"... {QUOTE} ..."}
        for i in range(spans)
    ]
    return JsonCorpus({ACC: {"acceptance_timestamp": acceptance, "spans": span_list}})


# --- happy paths -----------------------------------------------------------
def test_structural_only_compiles_and_pins_checksum() -> None:
    manifest = compile_manifest([_record()])
    assert manifest.resolved is False
    assert len(manifest.entries) == 1
    assert manifest.checksum.startswith("sha256:")
    # Deterministic: recompiling yields the identical digest.
    assert compile_manifest([_record()]).checksum == manifest.checksum


def test_resolution_sets_span_id_and_checksum_differs_from_structural() -> None:
    structural = compile_manifest([_record()])
    resolved = compile_manifest([_record()], corpus=_corpus(), corpus_version_id="cv-1")
    assert resolved.resolved is True
    assert resolved.entries[0].evidence[0].span_id == "span-0"
    assert resolved.checksum != structural.checksum


def test_range_and_scale_normalisation() -> None:
    record = _record(
        expected_answer={
            "kind": "numeric",
            "value": "729-734",
            "unit": "USD",
            "scale": "millions",
            "period": "Q2 FY2027",
        }
    )
    entry = compile_manifest([record]).entries[0]
    answer = entry.expected_answer.to_dict()  # type: ignore[union-attr]
    assert answer["low"] == "729" and answer["high"] == "734"
    assert answer["scale_exponent"] == 6


def test_text_and_negative_records_compile() -> None:
    text = _record(id="BM-T", expected_answer={"kind": "text", "text": "Deferred revenue rose."})
    negative = _record(
        id="BM-N", answerable=False, expected_answer=None, evidence=[], documents_reviewed=[ACC]
    )
    manifest = compile_manifest([text, negative])
    assert len(manifest.entries) == 2


# --- failure rules ---------------------------------------------------------
def _codes(records: list[dict[str, Any]], **kw: Any) -> set[str]:
    with pytest.raises(CompilationError) as exc:
        compile_manifest(records, **kw)
    return {v.code for v in exc.value.violations}


def test_temporal_leakage_accepted_after_cutoff() -> None:
    corpus = _corpus(acceptance="2026-06-01T12:00:00Z")  # after the 2026-05-28 cutoff
    assert "TEMPORAL_LEAKAGE" in _codes([_record()], corpus=corpus)


def test_provisional_midnight_same_day_fails() -> None:
    # Cutoff is midnight and the filing was accepted that same day -> unorderable.
    corpus = _corpus(acceptance="2026-05-28T09:00:00Z")
    assert "TEMPORAL_LEAKAGE" in _codes([_record()], corpus=corpus)


def test_ambiguous_anchor_fails() -> None:
    assert "AMBIGUOUS_ANCHOR" in _codes([_record()], corpus=_corpus(spans=2))


def test_unresolved_anchor_fails() -> None:
    assert "UNRESOLVED_ANCHOR" in _codes([_record()], corpus=_corpus(spans=0))


def test_zero_denominator_fails() -> None:
    record = _record(
        expected_answer={
            "kind": "numeric",
            "value": "100/0",
            "unit": "percent",
            "scale": "ones",
            "period": "FY2027",
        }
    )
    assert "ZERO_DENOMINATOR" in _codes([record])


def test_negative_case_without_scope_fails() -> None:
    record = _record(
        id="BM-N", answerable=False, expected_answer=None, evidence=[], documents_reviewed=[]
    )
    assert "NEGATIVE_SCOPE_MISSING" in _codes([record])


def test_unknown_scale_and_invalid_range_and_bad_accession() -> None:
    assert "UNKNOWN_SCALE" in _codes(
        [_record(expected_answer={**_record()["expected_answer"], "scale": "zillions"})]
    )
    assert "INVALID_RANGE" in _codes(
        [_record(expected_answer={**_record()["expected_answer"], "value": "5-3"})]
    )
    assert "MALFORMED_RECORD" in _codes(
        [
            _record(
                evidence=[{"accession": "bad", "form": "8-K", "section": SECTION, "quote": QUOTE}]
            )
        ]
    )


def test_duplicate_record_id_fails() -> None:
    assert "MALFORMED_RECORD" in _codes([_record(), _record()])


def test_all_violations_aggregated() -> None:
    bad_scale = _record(id="A", expected_answer={**_record()["expected_answer"], "scale": "x"})
    bad_neg = _record(
        id="B", answerable=False, expected_answer=None, evidence=[], documents_reviewed=[]
    )
    with pytest.raises(CompilationError) as exc:
        compile_manifest([bad_scale, bad_neg])
    ids = {v.record_id for v in exc.value.violations}
    assert ids == {"A", "B"}


# --- real 65-question seed -------------------------------------------------
def _seed_path() -> Path:
    return Path(__file__).resolve().parents[3] / "evals/datasets/benchmark-seed/questions.jsonl"


def test_real_seed_structural_compile() -> None:
    """The reconciled PR #74 seed compiles structurally (offline, no corpus) to a
    checksum-pinned 65-question manifest; its negative cases declare scope."""
    seed_path = _seed_path()
    if not seed_path.exists():  # pragma: no cover - seed is committed
        pytest.skip("benchmark seed not present")
    records = load_seed(seed_path)
    assert len(records) == 65
    manifest = compile_manifest(records)
    assert len(manifest.entries) == 65
    assert manifest.checksum.startswith("sha256:")
    # Deterministic recompile.
    assert compile_manifest(load_seed(seed_path)).checksum == manifest.checksum
    negatives = [e for e in manifest.entries if not e.answerable]
    assert negatives and all(e.documents_reviewed for e in negatives)
