"""Strict offline extraction-calibration-dataset/v1 validator (#336)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import NoReturn, cast

_MAX_BYTES = 64 * 1024 * 1024
_MAX_RECORDS = 100000
_MAX_ISSUERS = 1000
_MAX_STRATA = 10000
_MAX_DEPTH = 16
_SCHEMA = "extraction-calibration-dataset/v1"
_SUPPORT_SCHEMA = "calibration-support/v1"
_EVIDENCE = frozenset({"synthetic", "adjudicated"})
_SPLITS = ("train", "calibration", "evaluation")
_SPLIT_SET = frozenset(_SPLITS)
_FAMILIES = frozenset({"kpi", "guidance", "revenue_driver"})
_DATASET_KEYS = frozenset(
    {
        "schema_version",
        "dataset_id",
        "evidence_kind",
        "pins",
        "split_manifest",
        "records",
    }
)
_PIN_KEYS = (
    "ontology_sha256",
    "workflow_sha256",
    "prompts_sha256",
    "model_sha256",
    "score_definition_sha256",
)
_PIN_KEY_SET = frozenset(_PIN_KEYS)
_SPLIT_KEYS = frozenset({"issuer_ids", "start_at", "end_at"})
_RECORD_KEYS = frozenset(
    {
        "sample_id",
        "proposal_sha256",
        "issuer_id",
        "source_sha256",
        "published_at",
        "as_of",
        "adjudicated_at",
        "split",
        "family",
        "field",
        "score",
        "outcome",
        "reviewer_ids",
    }
)
_HASH = re.compile(r"[0-9a-f]{64}")
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SCORE = re.compile(r"(?:0|1|0\.[0-9]{0,11}[1-9])")
_STAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_CODES = frozenset(
    {
        "invalid_json",
        "invalid_shape",
        "invalid_identity",
        "invalid_score",
        "invalid_time",
        "duplicate_sample",
        "split_leakage",
        "limit_exceeded",
    }
)
_MESSAGES = {
    "invalid_json": "Calibration dataset JSON is invalid",
    "invalid_shape": "Calibration dataset shape is invalid",
    "invalid_identity": "Calibration dataset identity is invalid",
    "invalid_score": "Calibration dataset score is invalid",
    "invalid_time": "Calibration dataset chronology is invalid",
    "duplicate_sample": "Calibration dataset sample identity is duplicated",
    "split_leakage": "Calibration dataset split isolation is violated",
    "limit_exceeded": "Calibration dataset resource bound is exceeded",
}


class CalibrationDatasetError(Exception):
    """Safe validation failure; ``code`` is a frozen diagnostic token."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class _DuplicateKeys(ValueError):
    """JSON object contained a repeated key."""


def _fail(code: str) -> NoReturn:
    if code not in _CODES:
        raise RuntimeError("unknown calibration dataset error")
    error = CalibrationDatasetError(_MESSAGES[code], code=code)
    error.__cause__ = None
    error.__context__ = None
    error.__suppress_context__ = True
    raise error


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeys
        result[key] = value
    return result


def _reject_float(_text: str) -> None:
    raise ValueError("float")


def _reject_constant(_text: str) -> None:
    raise ValueError("constant")


def _check_depth(value: object, depth: int) -> None:
    kind = type(value)
    if kind is dict:
        if depth > _MAX_DEPTH:
            _fail("limit_exceeded")
        for inner in cast(dict[str, object], value).values():
            _check_depth(inner, depth + 1)
    elif kind is list:
        if depth > _MAX_DEPTH:
            _fail("limit_exceeded")
        for inner in cast(list[object], value):
            _check_depth(inner, depth + 1)


def _decode(raw: bytes) -> object:
    if type(raw) is not bytes:
        _fail("invalid_json")
    if len(raw) > _MAX_BYTES:
        _fail("limit_exceeded")
    decode_failed = False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        decode_failed = True
        text = ""
    if decode_failed:
        _fail("invalid_json")
    if text.startswith("\ufeff"):
        _fail("invalid_json")
    decoder = json.JSONDecoder(
        object_pairs_hook=_object_pairs,
        parse_float=_reject_float,
        parse_constant=_reject_constant,
        strict=True,
    )
    payload: object = None
    index = 0
    failure: str | None = None
    try:
        payload, index = decoder.raw_decode(text)
    except _DuplicateKeys:
        failure = "invalid_json"
    except RecursionError:
        failure = "limit_exceeded"
    except json.JSONDecodeError:
        failure = "invalid_json"
    except ValueError:
        failure = "invalid_json"
    if failure is not None:
        _fail(failure)
    if text[index:].strip() != "":
        _fail("invalid_json")
    depth_failed = False
    try:
        _check_depth(payload, 1)
    except RecursionError:
        depth_failed = True
    if depth_failed:
        _fail("limit_exceeded")
    return payload


def _require_dict(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail("invalid_shape")
    for key in value:
        if type(key) is not str:
            _fail("invalid_shape")
    return value


def _require_list(value: object) -> list[object]:
    if type(value) is not list:
        _fail("invalid_shape")
    return value


def _require_str(value: object, *, code: str = "invalid_shape") -> str:
    if type(value) is not str:
        _fail(code)
    return value


def _require_int(value: object) -> int:
    if type(value) is not int:
        _fail("invalid_shape")
    return value


def _canonical_uuid(value: object) -> str:
    text = _require_str(value, code="invalid_identity")
    parsed: uuid.UUID | None = None
    invalid = False
    try:
        parsed = uuid.UUID(text)
    except ValueError:
        invalid = True
    if invalid or parsed is None or text != str(parsed):
        _fail("invalid_identity")
    return str(parsed)


def _canonical_hash(value: object) -> str:
    text = _require_str(value, code="invalid_identity")
    if _HASH.fullmatch(text) is None:
        _fail("invalid_identity")
    return text


def _canonical_score(value: object) -> str:
    text = _require_str(value, code="invalid_score")
    if _SCORE.fullmatch(text) is None:
        _fail("invalid_score")
    return text


def _canonical_stamp(value: object) -> tuple[str, datetime]:
    text = _require_str(value, code="invalid_time")
    matched = _STAMP.fullmatch(text)
    if matched is None:
        _fail("invalid_time")
    year, month, day, hour, minute, second = (int(part) for part in matched.groups())
    instant: datetime | None = None
    invalid = False
    try:
        instant = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        invalid = True
    if invalid or instant is None:
        _fail("invalid_time")
    canonical = (
        f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}"
        f"T{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}Z"
    )
    if canonical != text:
        _fail("invalid_time")
    return text, instant


def _unique_uuids(values: object, *, limit: int) -> list[str]:
    items = _require_list(values)
    if len(items) > limit:
        _fail("limit_exceeded")
    if len(items) == 0:
        _fail("invalid_shape")
    parsed = [_canonical_uuid(item) for item in items]
    if len(set(parsed)) != len(parsed):
        _fail("invalid_identity")
    return sorted(parsed)


def _pins(value: object) -> dict[str, str]:
    pins = _require_dict(value)
    if set(pins) != _PIN_KEY_SET:
        _fail("invalid_shape")
    return {key: _canonical_hash(pins[key]) for key in _PIN_KEYS}


def _split_window(value: object) -> dict[str, object]:
    block = _require_dict(value)
    if set(block) != _SPLIT_KEYS:
        _fail("invalid_shape")
    issuers = _unique_uuids(block["issuer_ids"], limit=_MAX_ISSUERS)
    start_text, start_at = _canonical_stamp(block["start_at"])
    end_text, end_at = _canonical_stamp(block["end_at"])
    if start_at > end_at:
        _fail("invalid_time")
    return {
        "issuer_ids": issuers,
        "start_at": start_text,
        "end_at": end_text,
        "_start": start_at,
        "_end": end_at,
        "_issuers": set(issuers),
    }


def _split_manifest(value: object) -> dict[str, dict[str, object]]:
    manifest = _require_dict(value)
    if set(manifest) != _SPLIT_SET:
        _fail("invalid_shape")
    parsed = {name: _split_window(manifest[name]) for name in _SPLITS}
    train_end = parsed["train"]["_end"]
    calibration_start = parsed["calibration"]["_start"]
    calibration_end = parsed["calibration"]["_end"]
    evaluation_start = parsed["evaluation"]["_start"]
    if not isinstance(train_end, datetime) or not isinstance(calibration_start, datetime):
        _fail("invalid_time")
    if not isinstance(calibration_end, datetime) or not isinstance(evaluation_start, datetime):
        _fail("invalid_time")
    if not (train_end < calibration_start and calibration_end < evaluation_start):
        _fail("invalid_time")
    issuer_sets = []
    for name in _SPLITS:
        issuers = parsed[name]["_issuers"]
        if not isinstance(issuers, set):
            _fail("invalid_shape")
        issuer_sets.append(issuers)
    for index, left in enumerate(issuer_sets):
        for right in issuer_sets[index + 1 :]:
            if left & right:
                _fail("split_leakage")
    return parsed


def _reviewers(value: object, *, evidence_kind: str) -> list[str]:
    items = _require_list(value)
    parsed = [_canonical_uuid(item) for item in items]
    if len(set(parsed)) != len(parsed):
        _fail("invalid_identity")
    if evidence_kind == "synthetic":
        if parsed:
            _fail("invalid_identity")
        return []
    if len(parsed) != 2:
        _fail("invalid_identity")
    return sorted(parsed)


def _record(
    value: object,
    *,
    evidence_kind: str,
    splits: dict[str, dict[str, object]],
    sample_ids: set[str],
    proposal_fields: set[tuple[str, str, str]],
    proposal_split: dict[str, str],
    proposal_meta: dict[str, tuple[str, str, str, str, str, str]],
    source_split: dict[str, str],
    strata: set[tuple[str, str]],
) -> dict[str, object]:
    record = _require_dict(value)
    if set(record) != _RECORD_KEYS:
        _fail("invalid_shape")
    sample_id = _canonical_uuid(record["sample_id"])
    if sample_id in sample_ids:
        _fail("duplicate_sample")
    sample_ids.add(sample_id)
    proposal = _canonical_hash(record["proposal_sha256"])
    issuer_id = _canonical_uuid(record["issuer_id"])
    source = _canonical_hash(record["source_sha256"])
    published, published_at = _canonical_stamp(record["published_at"])
    as_of_text, as_of = _canonical_stamp(record["as_of"])
    adjudicated, adjudicated_at = _canonical_stamp(record["adjudicated_at"])
    if not (published_at <= as_of <= adjudicated_at):
        _fail("invalid_time")
    split = _require_str(record["split"])
    if split not in _SPLIT_SET:
        _fail("invalid_shape")
    family = _require_str(record["family"])
    if family not in _FAMILIES:
        _fail("invalid_shape")
    field = _require_str(record["field"], code="invalid_identity")
    if _FIELD.fullmatch(field) is None:
        _fail("invalid_identity")
    score = _canonical_score(record["score"])
    outcome = _require_int(record["outcome"])
    if outcome not in (0, 1):
        _fail("invalid_shape")
    reviewers = _reviewers(record["reviewer_ids"], evidence_kind=evidence_kind)
    key = (proposal, family, field)
    if key in proposal_fields:
        _fail("duplicate_sample")
    proposal_fields.add(key)
    if proposal in proposal_split and proposal_split[proposal] != split:
        _fail("split_leakage")
    meta = (issuer_id, source, published, as_of_text, adjudicated, split)
    if proposal in proposal_meta and proposal_meta[proposal] != meta:
        _fail("invalid_identity")
    proposal_split[proposal] = split
    proposal_meta[proposal] = meta
    if source in source_split and source_split[source] != split:
        _fail("split_leakage")
    source_split[source] = split
    window = splits[split]
    issuers = window["_issuers"]
    start_at = window["_start"]
    end_at = window["_end"]
    if not isinstance(issuers, set) or issuer_id not in issuers:
        _fail("split_leakage")
    if not isinstance(start_at, datetime) or not isinstance(end_at, datetime):
        _fail("invalid_time")
    if not (start_at <= published_at <= end_at):
        _fail("invalid_time")
    strata.add((family, field))
    if len(strata) > _MAX_STRATA:
        _fail("limit_exceeded")
    return {
        "sample_id": sample_id,
        "proposal_sha256": proposal,
        "issuer_id": issuer_id,
        "source_sha256": source,
        "published_at": published,
        "as_of": as_of_text,
        "adjudicated_at": adjudicated,
        "split": split,
        "family": family,
        "field": field,
        "score": score,
        "outcome": outcome,
        "reviewer_ids": reviewers,
    }


def _public_split(block: dict[str, object]) -> dict[str, object]:
    issuers = block["issuer_ids"]
    if not isinstance(issuers, list):
        _fail("invalid_shape")
    return {
        "issuer_ids": list(issuers),
        "start_at": block["start_at"],
        "end_at": block["end_at"],
    }


def _cross_split_cutoff(records: list[dict[str, object]]) -> None:
    grouped: dict[str, list[dict[str, object]]] = {name: [] for name in _SPLITS}
    for record in records:
        split = record["split"]
        if not isinstance(split, str):
            _fail("invalid_shape")
        grouped[split].append(record)

    def _max_as_of(name: str) -> datetime | None:
        rows = grouped[name]
        if not rows:
            return None
        return max(_canonical_stamp(row["as_of"])[1] for row in rows)

    def _min_published(name: str) -> datetime | None:
        rows = grouped[name]
        if not rows:
            return None
        return min(_canonical_stamp(row["published_at"])[1] for row in rows)

    train_as_of = _max_as_of("train")
    calibration_published = _min_published("calibration")
    calibration_as_of = _max_as_of("calibration")
    evaluation_published = _min_published("evaluation")
    if train_as_of is not None and calibration_published is not None:
        if not (train_as_of < calibration_published):
            _fail("invalid_time")
    if calibration_as_of is not None and evaluation_published is not None:
        if not (calibration_as_of < evaluation_published):
            _fail("invalid_time")
    if train_as_of is not None and evaluation_published is not None:
        if not (train_as_of < evaluation_published):
            _fail("invalid_time")


def _validate(payload: object) -> dict[str, object]:
    dataset = _require_dict(payload)
    if set(dataset) != _DATASET_KEYS:
        _fail("invalid_shape")
    if _require_str(dataset["schema_version"]) != _SCHEMA:
        _fail("invalid_shape")
    dataset_id = _canonical_uuid(dataset["dataset_id"])
    evidence_kind = _require_str(dataset["evidence_kind"])
    if evidence_kind not in _EVIDENCE:
        _fail("invalid_shape")
    pins = _pins(dataset["pins"])
    splits = _split_manifest(dataset["split_manifest"])
    raw_records = _require_list(dataset["records"])
    if len(raw_records) > _MAX_RECORDS:
        _fail("limit_exceeded")
    sample_ids: set[str] = set()
    proposal_fields: set[tuple[str, str, str]] = set()
    proposal_split: dict[str, str] = {}
    proposal_meta: dict[str, tuple[str, str, str, str, str, str]] = {}
    source_split: dict[str, str] = {}
    strata: set[tuple[str, str]] = set()
    records = [
        _record(
            item,
            evidence_kind=evidence_kind,
            splits=splits,
            sample_ids=sample_ids,
            proposal_fields=proposal_fields,
            proposal_split=proposal_split,
            proposal_meta=proposal_meta,
            source_split=source_split,
            strata=strata,
        )
        for item in raw_records
    ]
    records.sort(key=lambda row: str(row["sample_id"]))
    _cross_split_cutoff(records)
    return {
        "schema_version": _SCHEMA,
        "dataset_id": dataset_id,
        "evidence_kind": evidence_kind,
        "pins": pins,
        "split_manifest": {name: _public_split(splits[name]) for name in _SPLITS},
        "records": records,
    }


def _reject_dict_floats(value: object) -> None:
    if type(value) is float:
        _fail("invalid_json")
    kind = type(value)
    if kind is dict:
        for inner in cast(dict[str, object], value).values():
            _reject_dict_floats(inner)
    elif kind is list:
        for inner in cast(list[object], value):
            _reject_dict_floats(inner)


def _validated(dataset: object) -> dict[str, object]:
    depth_failed = False
    try:
        _check_depth(dataset, 1)
    except RecursionError:
        depth_failed = True
    if depth_failed:
        _fail("limit_exceeded")
    _reject_dict_floats(dataset)
    return _validate(dataset)


def _dump(dataset: dict[str, object]) -> bytes:
    return json.dumps(
        dataset,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def load_dataset(raw: bytes) -> dict[str, object]:
    """Return a normalized, fully validated dataset from UTF-8 JSON bytes."""
    return _validate(_decode(raw))


def canonical_dataset_bytes(dataset: dict[str, object]) -> bytes:
    """Return canonical UTF-8 JSON bytes for a validated dataset object."""
    return _dump(_validated(dataset))


def dataset_digest(dataset: dict[str, object]) -> str:
    """Return the lowercase SHA-256 digest of the canonical dataset bytes."""
    return hashlib.sha256(canonical_dataset_bytes(dataset)).hexdigest()


def _sufficient(n: int, positive: int, negative: int) -> bool:
    return n >= 100 and positive >= 20 and negative >= 20


def support_report(dataset: dict[str, object]) -> dict[str, object]:
    """Return the frozen per-stratum support report for a validated dataset."""
    normalized = _validated(dataset)
    records_value = normalized["records"]
    if not isinstance(records_value, list):
        _fail("invalid_shape")
    digest = hashlib.sha256(_dump(normalized)).hexdigest()
    strata: set[tuple[str, str]] = set()
    counts: dict[tuple[str, str, str], list[int]] = {}
    for item in records_value:
        record = _require_dict(item)
        family = _require_str(record["family"])
        field = _require_str(record["field"])
        split = _require_str(record["split"])
        outcome = _require_int(record["outcome"])
        strata.add((family, field))
        key = (family, field, split)
        bucket = counts.setdefault(key, [0, 0])
        bucket[0] += 1
        if outcome == 1:
            bucket[1] += 1
    cells: list[dict[str, object]] = []
    ready = True
    for family, field in sorted(strata):
        for split in _SPLITS:
            n, positive = counts.get((family, field, split), [0, 0])
            negative = n - positive
            enough = _sufficient(n, positive, negative)
            cells.append(
                {
                    "family": family,
                    "field": field,
                    "split": split,
                    "n": n,
                    "positive": positive,
                    "negative": negative,
                    "sufficient": enough,
                }
            )
        calibration = counts.get((family, field, "calibration"), [0, 0])
        evaluation = counts.get((family, field, "evaluation"), [0, 0])
        if not (
            _sufficient(calibration[0], calibration[1], calibration[0] - calibration[1])
            and _sufficient(evaluation[0], evaluation[1], evaluation[0] - evaluation[1])
        ):
            ready = False
    cells.sort(key=lambda cell: (str(cell["family"]), str(cell["field"]), str(cell["split"])))
    if not strata:
        ready = False
        reason: str | None = "empty_dataset"
    elif ready:
        reason = None
    else:
        reason = "insufficient_support"
    return {
        "schema_version": _SUPPORT_SCHEMA,
        "dataset_sha256": digest,
        "evidence_kind": normalized["evidence_kind"],
        "ready": ready,
        "cells": cells,
        "reason": reason,
    }


__all__ = [
    "CalibrationDatasetError",
    "canonical_dataset_bytes",
    "dataset_digest",
    "load_dataset",
    "support_report",
]
