"""Failing-first regressions for the offline calibration dataset validator (#336)."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

import pytest

from harness.calibration_dataset import (
    CalibrationDatasetError,
    canonical_dataset_bytes,
    dataset_digest,
    load_dataset,
    support_report,
)

SCHEMA = "extraction-calibration-dataset/v1"
PIN_KEYS = (
    "ontology_sha256",
    "workflow_sha256",
    "prompts_sha256",
    "model_sha256",
    "score_definition_sha256",
)
SPLITS = ("train", "calibration", "evaluation")
WINDOWS = {
    "train": ("2020-01-01T00:00:00Z", "2020-06-30T23:59:59Z"),
    "calibration": ("2020-07-01T00:00:00Z", "2020-12-31T23:59:59Z"),
    "evaluation": ("2021-01-01T00:00:00Z", "2021-06-30T23:59:59Z"),
}
TIMES = {
    "train": ("2020-03-01T00:00:00Z", "2020-03-02T00:00:00Z", "2020-03-03T00:00:00Z"),
    "calibration": ("2020-09-01T00:00:00Z", "2020-09-02T00:00:00Z", "2020-09-03T00:00:00Z"),
    "evaluation": ("2021-03-01T00:00:00Z", "2021-03-02T00:00:00Z", "2021-03-03T00:00:00Z"),
}


def _uuid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-cal:{tag}"))


def _sha(tag: str) -> str:
    return hashlib.sha256(f"synthetic-cal:{tag}".encode()).hexdigest()


def _pins() -> dict[str, str]:
    return {key: _sha(f"pin:{key}") for key in PIN_KEYS}


def _split_manifest() -> dict[str, object]:
    return {
        name: {
            "issuer_ids": [_uuid(f"issuer-{name}")],
            "start_at": WINDOWS[name][0],
            "end_at": WINDOWS[name][1],
        }
        for name in SPLITS
    }


def _record(
    *,
    sample: str,
    split: str,
    family: str = "kpi",
    field: str = "arr",
    score: str = "0.5",
    outcome: int = 1,
    proposal: str | None = None,
    source: str | None = None,
    issuer: str | None = None,
    reviewers: list[str] | None = None,
    published_at: str | None = None,
    as_of: str | None = None,
    adjudicated_at: str | None = None,
) -> dict[str, object]:
    published, as_of_value, adjudicated = TIMES[split]
    return {
        "sample_id": sample,
        "proposal_sha256": proposal if proposal is not None else _sha(f"proposal:{sample}"),
        "issuer_id": issuer if issuer is not None else _uuid(f"issuer-{split}"),
        "source_sha256": source if source is not None else _sha(f"source:{split}"),
        "published_at": published_at if published_at is not None else published,
        "as_of": as_of if as_of is not None else as_of_value,
        "adjudicated_at": adjudicated_at if adjudicated_at is not None else adjudicated,
        "split": split,
        "family": family,
        "field": field,
        "score": score,
        "outcome": outcome,
        "reviewer_ids": [] if reviewers is None else reviewers,
    }


def _dataset(
    records: list[dict[str, object]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "dataset_id": _uuid("dataset"),
        "evidence_kind": "synthetic",
        "pins": _pins(),
        "split_manifest": _split_manifest(),
        "records": [] if records is None else records,
    }
    payload.update(overrides)
    return payload


def _dumps(payload: dict[str, object], **kwargs: object) -> bytes:
    return json.dumps(payload, **kwargs).encode("utf-8")


def _rows(split: str, n: int, n_positive: int, *, field: str = "arr") -> list[dict[str, object]]:
    rows = []
    for index in range(n):
        rows.append(
            _record(
                sample=_uuid(f"{split}:{field}:{index}"),
                split=split,
                field=field,
                outcome=1 if index < n_positive else 0,
                score="0.5" if index % 2 == 0 else "0.25",
            )
        )
    return rows


def _ready_records(*, field: str = "arr") -> list[dict[str, object]]:
    return [
        *_rows("calibration", 100, 20, field=field),
        *_rows("evaluation", 100, 20, field=field),
    ]


def _code(raw: bytes | dict[str, object], code: str) -> None:
    with pytest.raises(CalibrationDatasetError) as caught:
        if isinstance(raw, bytes):
            load_dataset(raw)
        else:
            canonical_dataset_bytes(raw)
    assert caught.value.code == code
    message = str(caught.value)
    assert "\n" not in message
    lowered = message.lower()
    assert "traceback" not in lowered
    assert "json.decoder" not in lowered


def test_empty_dataset_is_valid_and_not_ready() -> None:
    loaded = load_dataset(_dumps(_dataset()))
    assert loaded["records"] == []
    report = support_report(loaded)
    assert report["schema_version"] == "calibration-support/v1"
    assert report["evidence_kind"] == "synthetic"
    assert report["ready"] is False
    assert report["reason"] == "empty_dataset"
    assert report["cells"] == []
    assert report["dataset_sha256"] == dataset_digest(loaded)


def test_ready_report_requires_calibration_and_evaluation_support() -> None:
    loaded = load_dataset(_dumps(_dataset(_ready_records())))
    report = support_report(loaded)
    assert report["ready"] is True
    assert report["reason"] is None
    assert report["evidence_kind"] == "synthetic"
    cells = report["cells"]
    assert isinstance(cells, list)
    assert [cell["split"] for cell in cells] == ["calibration", "evaluation", "train"]
    by_split = {cell["split"]: cell for cell in cells}
    assert by_split["train"] == {
        "family": "kpi",
        "field": "arr",
        "split": "train",
        "n": 0,
        "positive": 0,
        "negative": 0,
        "sufficient": False,
    }
    assert by_split["calibration"]["n"] == 100
    assert by_split["calibration"]["positive"] == 20
    assert by_split["calibration"]["negative"] == 80
    assert by_split["calibration"]["sufficient"] is True
    assert by_split["evaluation"]["sufficient"] is True


def test_insufficient_train_only_does_not_block_ready() -> None:
    records = [
        *_rows("train", 19, 10),
        *_ready_records(),
    ]
    report = support_report(load_dataset(_dumps(_dataset(records))))
    assert report["ready"] is True
    train = next(cell for cell in report["cells"] if cell["split"] == "train")
    assert train["sufficient"] is False


@pytest.mark.parametrize(
    ("n", "n_positive"),
    [(99, 20), (100, 19), (100, 81)],
)
def test_support_boundary_is_exclusive_of_99_and_19(n: int, n_positive: int) -> None:
    records = [
        *_rows("calibration", n, n_positive),
        *_rows("evaluation", 100, 20),
    ]
    report = support_report(load_dataset(_dumps(_dataset(records))))
    assert report["ready"] is False
    assert report["reason"] == "insufficient_support"
    calibration = next(cell for cell in report["cells"] if cell["split"] == "calibration")
    assert calibration["sufficient"] is False


def test_missing_split_rows_are_zero_cells_not_dropped() -> None:
    records = _rows("calibration", 100, 20)
    report = support_report(load_dataset(_dumps(_dataset(records))))
    splits = [cell["split"] for cell in report["cells"]]
    assert splits == ["calibration", "evaluation", "train"]
    evaluation = next(cell for cell in report["cells"] if cell["split"] == "evaluation")
    assert evaluation["n"] == 0
    assert evaluation["sufficient"] is False
    assert report["ready"] is False


def test_observed_strata_are_the_union_across_splits() -> None:
    records = [
        *_rows("train", 5, 2, field="arr"),
        *_rows("calibration", 100, 20, field="bookings"),
        *_rows("evaluation", 100, 20, field="bookings"),
    ]
    report = support_report(load_dataset(_dumps(_dataset(records))))
    identities = [(cell["family"], cell["field"], cell["split"]) for cell in report["cells"]]
    assert identities == [
        ("kpi", "arr", "calibration"),
        ("kpi", "arr", "evaluation"),
        ("kpi", "arr", "train"),
        ("kpi", "bookings", "calibration"),
        ("kpi", "bookings", "evaluation"),
        ("kpi", "bookings", "train"),
    ]
    arr_cal = next(
        cell
        for cell in report["cells"]
        if cell["field"] == "arr" and cell["split"] == "calibration"
    )
    assert arr_cal["n"] == 0
    assert report["ready"] is False


def test_canonical_bytes_are_stable_under_key_and_row_permutation() -> None:
    records = _ready_records()
    baseline = _dataset(records)
    shuffled_records = list(reversed(records))
    reversed_keys = dict(reversed(list(baseline.items())))
    pins = dict(reversed(list(_pins().items())))
    reversed_keys["pins"] = pins
    reversed_keys["records"] = shuffled_records
    left = load_dataset(_dumps(baseline))
    right = load_dataset(_dumps(reversed_keys))
    assert canonical_dataset_bytes(left) == canonical_dataset_bytes(right)
    assert dataset_digest(left) == dataset_digest(right)
    assert b" " not in canonical_dataset_bytes(left)
    assert not canonical_dataset_bytes(left).endswith(b"\n")


def test_pin_change_alters_digest() -> None:
    loaded = load_dataset(_dumps(_dataset(_ready_records())))
    original = dataset_digest(loaded)
    pins = dict(loaded["pins"])
    pins["model_sha256"] = _sha("other-model")
    changed = dict(loaded)
    changed["pins"] = pins
    assert dataset_digest(changed) != original


def test_synthetic_support_never_reports_human_evidence() -> None:
    report = support_report(load_dataset(_dumps(_dataset(_ready_records()))))
    blob = json.dumps(report)
    assert report["evidence_kind"] == "synthetic"
    assert "adjudicat" not in blob
    assert "reviewer" not in blob
    assert "human" not in blob


def test_whitespace_input_canonicalizes_without_whitespace() -> None:
    pretty = json.dumps(_dataset(_ready_records()), indent=2, sort_keys=False).encode("utf-8")
    loaded = load_dataset(pretty)
    canonical = canonical_dataset_bytes(loaded)
    assert b"\n" not in canonical
    assert b" " not in canonical
    assert dataset_digest(loaded) == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"schema_version": "extraction-calibration-dataset/v1", "schema_version": "x"}',
        b"NaN",
        b"Infinity",
        b'{"score": NaN}',
        b'{"a": 1.5}',
    ],
)
def test_malformed_json_is_invalid_json(raw: bytes) -> None:
    _code(raw, "invalid_json")


@pytest.mark.parametrize("raw", [b"[]", b"null", b"1", b'"x"', b"true"])
def test_non_object_root_is_invalid_shape(raw: bytes) -> None:
    _code(raw, "invalid_shape")


def test_duplicate_nested_json_key_is_invalid_json() -> None:
    raw = (
        b'{"schema_version":"extraction-calibration-dataset/v1","dataset_id":"%s",'
        b'"evidence_kind":"synthetic","pins":{"ontology_sha256":"%s","ontology_sha256":"%s"},'
        b'"split_manifest":{},"records":[]}'
        % (_uuid("dataset").encode(), _sha("a").encode(), _sha("b").encode())
    )
    _code(raw, "invalid_json")


def test_bool_outcome_is_rejected() -> None:
    record = _record(sample=_uuid("bool"), split="train")
    record["outcome"] = True
    _code(_dumps(_dataset([record])), "invalid_shape")


def test_float_score_number_is_invalid_json() -> None:
    record = _record(sample=_uuid("float"), split="train")
    payload = _dataset([record])
    text = json.dumps(payload).replace('"0.5"', "0.5")
    _code(text.encode(), "invalid_json")


@pytest.mark.parametrize(
    "score",
    ["0.0", "0.10", "1.0", "01", "0.1234567890123", "+0.1", "0.1e1", "2", "0.", ".1", "00", "-0.1"],
)
def test_non_canonical_scores_are_rejected(score: str) -> None:
    record = _record(sample=_uuid(score), split="train", score=score)
    _code(_dumps(_dataset([record])), "invalid_score")


@pytest.mark.parametrize("score", ["0", "1", "0.1", "0.9", "0.123456789012", "0.000000000001"])
def test_canonical_score_boundaries_are_accepted(score: str) -> None:
    record = _record(sample=_uuid(f"ok-{score}"), split="train", score=score, outcome=0)
    loaded = load_dataset(_dumps(_dataset([record])))
    assert loaded["records"][0]["score"] == score


@pytest.mark.parametrize(
    "stamp",
    [
        "2020-13-01T00:00:00Z",
        "2020-02-30T00:00:00Z",
        "2020-01-01T00:00:00+00:00",
        "2020-01-01 00:00:00Z",
        "2020-01-01T00:00:00.000Z",
        "2020-01-01t00:00:00Z",
        "2020-01-01T24:00:00Z",
    ],
)
def test_invalid_utc_stamps_are_rejected(stamp: str) -> None:
    record = _record(sample=_uuid(stamp), split="train", published_at=stamp)
    _code(_dumps(_dataset([record])), "invalid_time")


def test_non_chronological_split_windows_are_rejected() -> None:
    manifest = _split_manifest()
    manifest["calibration"]["start_at"] = "2020-06-30T23:59:59Z"
    _code(_dumps(_dataset(split_manifest=manifest)), "invalid_time")


def test_published_after_as_of_is_rejected() -> None:
    record = _record(
        sample=_uuid("chrono"),
        split="train",
        published_at="2020-03-03T00:00:00Z",
        as_of="2020-03-02T00:00:00Z",
    )
    _code(_dumps(_dataset([record])), "invalid_time")


def test_as_of_crossing_later_split_publication_is_rejected() -> None:
    train = _record(
        sample=_uuid("late-as-of"),
        split="train",
        as_of="2020-09-01T00:00:00Z",
        adjudicated_at="2020-09-02T00:00:00Z",
    )
    calibration = _record(sample=_uuid("cal-pub"), split="calibration")
    _code(_dumps(_dataset([train, calibration])), "invalid_time")


def test_duplicate_sample_id_is_rejected() -> None:
    first = _record(sample=_uuid("dup"), split="train", field="arr")
    second = _record(sample=_uuid("dup"), split="train", field="bookings")
    _code(_dumps(_dataset([first, second])), "duplicate_sample")


def test_duplicate_proposal_field_is_rejected() -> None:
    proposal = _sha("same-proposal")
    first = _record(sample=_uuid("a"), split="train", proposal=proposal, field="arr")
    second = _record(sample=_uuid("b"), split="train", proposal=proposal, field="arr")
    _code(_dumps(_dataset([first, second])), "duplicate_sample")


def test_uppercase_uuid_is_invalid_identity() -> None:
    payload = _dataset()
    payload["dataset_id"] = _uuid("dataset").upper()
    _code(_dumps(payload), "invalid_identity")


def test_inconsistent_proposal_identity_is_rejected() -> None:
    proposal = _sha("shared")
    first = _record(sample=_uuid("a"), split="train", proposal=proposal, field="arr")
    second = _record(
        sample=_uuid("b"),
        split="train",
        proposal=proposal,
        field="bookings",
        issuer=_uuid("other-issuer-not-in-split"),
    )
    _code(_dumps(_dataset([first, second])), "invalid_identity")


def test_repeated_fields_of_one_proposal_must_share_metadata() -> None:
    proposal = _sha("multi-field")
    source = _sha("source:train")
    first = _record(sample=_uuid("a"), split="train", proposal=proposal, field="arr", source=source)
    second = _record(
        sample=_uuid("b"),
        split="train",
        proposal=proposal,
        field="bookings",
        source=source,
    )
    loaded = load_dataset(_dumps(_dataset([first, second])))
    assert len(loaded["records"]) == 2


def test_issuer_overlap_is_split_leakage() -> None:
    manifest = _split_manifest()
    shared = _uuid("issuer-train")
    manifest["calibration"]["issuer_ids"] = [shared]
    _code(_dumps(_dataset(split_manifest=manifest)), "split_leakage")


def test_source_overlap_across_splits_is_split_leakage() -> None:
    source = _sha("shared-source")
    train = _record(sample=_uuid("t"), split="train", source=source)
    calibration = _record(sample=_uuid("c"), split="calibration", source=source)
    _code(_dumps(_dataset([train, calibration])), "split_leakage")


def test_proposal_overlap_across_splits_is_split_leakage() -> None:
    proposal = _sha("shared-proposal")
    train = _record(sample=_uuid("t"), split="train", proposal=proposal, field="arr")
    calibration = _record(
        sample=_uuid("c"), split="calibration", proposal=proposal, field="bookings"
    )
    _code(_dumps(_dataset([train, calibration])), "split_leakage")


def test_record_issuer_outside_split_is_split_leakage() -> None:
    record = _record(
        sample=_uuid("wrong-issuer"),
        split="train",
        issuer=_uuid("issuer-calibration"),
    )
    _code(_dumps(_dataset([record])), "split_leakage")


def test_oversized_bytes_are_limit_exceeded() -> None:
    _code(b" " * (64 * 1024 * 1024 + 1), "limit_exceeded")


def test_record_limit_is_exclusive_of_100001() -> None:
    records = [_record(sample=_uuid(f"limit:{index}"), split="train") for index in range(100001)]
    _code(_dataset(records), "limit_exceeded")


def test_issuer_limit_is_exclusive_of_1001() -> None:
    manifest = _split_manifest()
    manifest["train"]["issuer_ids"] = [_uuid(f"issuer-{index}") for index in range(1001)]
    _code(_dataset(split_manifest=manifest), "limit_exceeded")


def test_stratum_limit_is_exclusive_of_10001() -> None:
    records = [
        _record(sample=_uuid(f"stratum:{index}"), split="train", field=f"f{index:04d}")
        for index in range(10001)
    ]
    _code(_dataset(records), "limit_exceeded")


def test_nesting_limit_is_16_containers() -> None:
    nested: Any = None
    for _ in range(17):
        nested = [nested]
    _code(json.dumps(nested).encode(), "limit_exceeded")


def test_unknown_top_level_key_is_invalid_shape() -> None:
    payload = _dataset()
    payload["extra"] = "nope"
    _code(_dumps(payload), "invalid_shape")


def test_unknown_record_key_is_invalid_shape() -> None:
    record = _record(sample=_uuid("extra"), split="train")
    record["text"] = "source excerpt"
    _code(_dumps(_dataset([record])), "invalid_shape")
    with pytest.raises(CalibrationDatasetError) as caught:
        load_dataset(_dumps(_dataset([record])))
    assert "source excerpt" not in str(caught.value)


def test_synthetic_records_cannot_claim_reviewers() -> None:
    record = _record(
        sample=_uuid("reviewers"),
        split="train",
        reviewers=[_uuid("r1"), _uuid("r2")],
    )
    _code(_dumps(_dataset([record])), "invalid_identity")


def test_adjudicated_records_require_two_distinct_reviewers() -> None:
    record = _record(sample=_uuid("adj"), split="train")
    payload = _dataset([record], evidence_kind="adjudicated")
    _code(_dumps(payload), "invalid_identity")
    record["reviewer_ids"] = [_uuid("r1"), _uuid("r1")]
    _code(_dumps(_dataset([record], evidence_kind="adjudicated")), "invalid_identity")
    record["reviewer_ids"] = [_uuid("r2"), _uuid("r1")]
    loaded = load_dataset(_dumps(_dataset([record], evidence_kind="adjudicated")))
    assert loaded["evidence_kind"] == "adjudicated"
    assert loaded["records"][0]["reviewer_ids"] == sorted([_uuid("r1"), _uuid("r2")])


def test_public_functions_validate_dicts_and_do_not_mutate_input() -> None:
    original = _dataset(_ready_records())
    snapshot = deepcopy(original)
    digest = dataset_digest(original)
    report = support_report(original)
    canonical = canonical_dataset_bytes(original)
    assert original == snapshot
    assert hashlib.sha256(canonical).hexdigest() == digest
    assert report["dataset_sha256"] == digest
    _code({"schema_version": SCHEMA}, "invalid_shape")


def test_error_codes_are_closed_and_messages_omit_payloads() -> None:
    record = _record(sample=_uuid("leak"), split="train")
    record["sample_id"] = "not-a-uuid"
    with pytest.raises(CalibrationDatasetError) as caught:
        load_dataset(_dumps(_dataset([record])))
    assert caught.value.code == "invalid_identity"
    assert "not-a-uuid" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_train_as_of_crossing_evaluation_with_empty_calibration_is_rejected() -> None:
    train = _record(
        sample=_uuid("empty-cal-train"),
        split="train",
        as_of="2021-05-01T00:00:00Z",
        adjudicated_at="2021-05-02T00:00:00Z",
    )
    evaluation = _record(sample=_uuid("empty-cal-eval"), split="evaluation")
    _code(_dumps(_dataset([train, evaluation])), "invalid_time")


def test_dict_float_values_are_invalid_json() -> None:
    record = _record(sample=_uuid("dict-float"), split="train")
    payload = _dataset([record])
    assert isinstance(payload["records"], list)
    records = payload["records"]
    assert isinstance(records, list)
    first = dict(records[0])  # type: ignore[union-attr]
    first["outcome"] = 1.5
    payload["records"] = [first]
    _code(payload, "invalid_json")
    first["outcome"] = 1
    first["score"] = 0.5
    payload["records"] = [first]
    _code(payload, "invalid_json")


def test_nesting_limit_counts_containers_not_scalar_leaves() -> None:
    sixteen: Any = None
    for _ in range(16):
        sixteen = [sixteen]
    # 16 containers + scalar leaf is within the 16-container bound:
    # depth passes, then shape fails because the root is not an object.
    _code(json.dumps(sixteen).encode(), "invalid_shape")


def test_early_utc_year_formats_without_platform_strftime() -> None:
    manifest = _split_manifest()
    manifest["train"]["start_at"] = "0001-01-01T00:00:00Z"
    manifest["train"]["end_at"] = "0001-06-30T23:59:59Z"
    manifest["calibration"]["start_at"] = "0001-07-01T00:00:00Z"
    manifest["calibration"]["end_at"] = "0001-12-31T23:59:59Z"
    manifest["evaluation"]["start_at"] = "0002-01-01T00:00:00Z"
    manifest["evaluation"]["end_at"] = "0002-06-30T23:59:59Z"
    record = _record(
        sample=_uuid("year-0001"),
        split="train",
        published_at="0001-03-01T00:00:00Z",
        as_of="0001-03-02T00:00:00Z",
        adjudicated_at="0001-03-03T00:00:00Z",
    )
    loaded = load_dataset(_dumps(_dataset([record], split_manifest=manifest)))
    assert loaded["records"][0]["published_at"] == "0001-03-01T00:00:00Z"
