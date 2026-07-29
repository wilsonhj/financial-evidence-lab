"""Load and validate saas-metrics.v1.json."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Any, TypeVar, get_args

from fel_ontology.models import (
    Family,
    MetricDef,
    MetricKind,
    OntologyDocument,
    PeriodSemantics,
    ValueType,
)

# Runtime enum vocabularies derived from the Literal aliases in models.py, so the
# declared type and the accepted JSON value can never drift apart. ``cast()`` is
# a no-op at runtime and these values come from a JSON file, so mypy cannot
# check them either — without an explicit membership test the Literal types are
# decorative and ``value_type: "not_a_type"`` loads cleanly.
METRIC_KINDS: tuple[MetricKind, ...] = get_args(MetricKind)
VALUE_TYPES: tuple[ValueType, ...] = get_args(ValueType)
PERIOD_SEMANTICS: tuple[PeriodSemantics, ...] = get_args(PeriodSemantics)

EXPECTED_METRIC_IDS: frozenset[str] = frozenset(
    {
        "arr",
        "mrr",
        "nrr",
        "grr",
        "cust_total",
        "cust_threshold",
        "seats",
        "bookings",
        "billings",
        "rpo",
        "crpo",
        "deferred_rev",
        "sub_gm",
        "svc_gm",
    }
)

EXPECTED_FAMILY_COUNT = 9


class OntologyLoadError(ValueError):
    """Raised when the ontology document fails structural validation."""


def ontology_content_hash(raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest}"


def _require_str_list(obj: dict[str, Any], key: str) -> tuple[str, ...]:
    """Require a list of non-empty strings that is itself non-empty.

    ``all(...)`` is vacuously True on ``[]``, so the previous form accepted an
    empty list despite its own "non-empty" message. That is not cosmetic for
    ``comparability_key_fields``: ``build_comparability_key`` joins the fields
    it is given, so an empty list yields the empty key for every fact and makes
    every fact comparable to every other one.
    """
    value = obj.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise OntologyLoadError(f"metric/family field {key!r} must be a non-empty string list")
    return tuple(value)


_Choice = TypeVar("_Choice", bound=str)


def _require_choice(
    metric_id: str, obj: dict[str, Any], key: str, allowed: tuple[_Choice, ...]
) -> _Choice:
    """Validate a JSON string against a declared Literal vocabulary.

    Returns a member of ``allowed``, so the narrowed Literal type on
    :class:`~fel_ontology.models.MetricDef` is produced by a real membership
    test rather than an unchecked ``cast``.
    """
    value = obj.get(key)
    for candidate in allowed:
        if value == candidate:
            return candidate
    raise OntologyLoadError(
        f"metric {metric_id} field {key!r} must be one of {sorted(allowed)}, got {value!r}"
    )


def load_saas_metrics(*, path: str | None = None) -> OntologyDocument:
    """Load the packaged (or path-override) saas-metrics/v1 ontology."""
    if path is None:
        raw = resources.files("fel_ontology.data").joinpath("saas-metrics.v1.json").read_bytes()
    else:
        with open(path, "rb") as fh:
            raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise OntologyLoadError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise OntologyLoadError("ontology root must be an object")
    if data.get("schema_version") != "saas-metrics/v1":
        raise OntologyLoadError("schema_version must be saas-metrics/v1")
    if data.get("ontology_id") != "saas-metrics":
        raise OntologyLoadError("ontology_id must be saas-metrics")

    limitations = data.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(x, str) for x in limitations):
        raise OntologyLoadError("limitations must be a list of strings")

    families_raw = data.get("families")
    metrics_raw = data.get("metrics")
    if not isinstance(families_raw, list) or not isinstance(metrics_raw, list):
        raise OntologyLoadError("families and metrics must be arrays")
    if len(families_raw) != EXPECTED_FAMILY_COUNT:
        raise OntologyLoadError(
            f"expected {EXPECTED_FAMILY_COUNT} families, got {len(families_raw)}"
        )

    families: list[Family] = []
    family_ids: set[str] = set()
    for fam in families_raw:
        if not isinstance(fam, dict):
            raise OntologyLoadError("family entries must be objects")
        fid = fam.get("id")
        name = fam.get("name")
        if not isinstance(fid, str) or not isinstance(name, str):
            raise OntologyLoadError("family id/name must be strings")
        if fid in family_ids:
            raise OntologyLoadError(f"duplicate family id: {fid}")
        family_ids.add(fid)
        families.append(Family(id=fid, name=name, metric_ids=_require_str_list(fam, "metric_ids")))

    metrics: list[MetricDef] = []
    metric_ids: set[str] = set()
    for m in metrics_raw:
        if not isinstance(m, dict):
            raise OntologyLoadError("metric entries must be objects")
        mid = m.get("id")
        if not isinstance(mid, str):
            raise OntologyLoadError("metric id must be a string")
        if mid in metric_ids:
            raise OntologyLoadError(f"duplicate metric id: {mid}")
        metric_ids.add(mid)
        family_id = m.get("family_id")
        if family_id not in family_ids:
            raise OntologyLoadError(f"metric {mid} references unknown family {family_id!r}")
        required = (
            "canonical_name",
            "kind",
            "value_type",
            "unit",
            "period_semantics",
            "scale_handling",
            "derivation_policy",
            "review_policy",
        )
        for key in required:
            if not isinstance(m.get(key), str) or not m.get(key):
                raise OntologyLoadError(f"metric {mid} missing string field {key}")
        metrics.append(
            MetricDef(
                id=mid,
                canonical_name=str(m["canonical_name"]),
                family_id=str(family_id),
                kind=_require_choice(mid, m, "kind", METRIC_KINDS),
                value_type=_require_choice(mid, m, "value_type", VALUE_TYPES),
                unit=str(m["unit"]),
                period_semantics=_require_choice(mid, m, "period_semantics", PERIOD_SEMANTICS),
                scale_handling=str(m["scale_handling"]),
                aliases=_require_str_list(m, "aliases"),
                required_qualifiers=_require_str_list(m, "required_qualifiers"),
                comparability_key_fields=_require_str_list(m, "comparability_key_fields"),
                derivation_policy=str(m["derivation_policy"]),
                review_policy=str(m["review_policy"]),
                notes=str(m.get("notes") or ""),
            )
        )

    if metric_ids != EXPECTED_METRIC_IDS:
        missing = sorted(EXPECTED_METRIC_IDS - metric_ids)
        extra = sorted(metric_ids - EXPECTED_METRIC_IDS)
        raise OntologyLoadError(f"metric id set mismatch; missing={missing} extra={extra}")

    # Family membership must cover every metric exactly once.
    claimed: list[str] = []
    for fam in families:
        claimed.extend(fam.metric_ids)
    if sorted(claimed) != sorted(metric_ids):
        raise OntologyLoadError("family metric_ids must partition the metric set")

    return OntologyDocument(
        schema_version="saas-metrics/v1",
        ontology_id="saas-metrics",
        limitations=tuple(limitations),
        families=tuple(families),
        metrics=tuple(metrics),
        content_hash=ontology_content_hash(raw),
    )
