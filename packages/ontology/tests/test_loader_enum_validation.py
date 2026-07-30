"""The loader must reject values outside the declared Literal vocabularies.

``cast()`` is a runtime no-op and every field here originates in a JSON file,
so mypy cannot check it either: before this the ``Literal`` aliases in
``models.py`` were decorative and a data file carrying
``value_type: "not_a_type"`` loaded cleanly.

Each mutation test doctors the packaged document, writes it to a temp path, and
loads it through the ``path=`` override, so the packaged data file is never
touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fel_ontology.loader import (
    METRIC_KINDS,
    PERIOD_SEMANTICS,
    VALUE_TYPES,
    OntologyLoadError,
    load_saas_metrics,
)
from fel_ontology.models import MetricKind, PeriodSemantics, ValueType

_PACKAGED = Path(__file__).resolve().parents[1] / "fel_ontology" / "data" / "saas-metrics.v1.json"


def _document() -> dict[str, Any]:
    loaded = json.loads(_PACKAGED.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write(tmp_path: Path, doc: dict[str, Any]) -> str:
    target = tmp_path / "saas-metrics.v1.json"
    target.write_text(json.dumps(doc), encoding="utf-8")
    return str(target)


def test_unmutated_copy_still_loads(tmp_path: Path) -> None:
    """Control: the harness itself does not break a healthy document."""
    doc = load_saas_metrics(path=_write(tmp_path, _document()))
    assert doc.metric("arr").value_type == "currency"


def test_runtime_vocabularies_match_the_literal_aliases() -> None:
    """The accepted values are *derived* from models.py, never restated."""
    from typing import get_args

    assert METRIC_KINDS == get_args(MetricKind)
    assert VALUE_TYPES == get_args(ValueType)
    assert PERIOD_SEMANTICS == get_args(PeriodSemantics)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("kind", "not_a_kind"),
        ("kind", "Flow"),  # case matters; the Literal is exact
        ("value_type", "not_a_type"),
        ("value_type", "currency_derived_x"),
        ("period_semantics", "not_a_semantics"),
        ("period_semantics", "point_in_time"),  # a plausible-looking near miss
        ("kind", None),
        ("value_type", 7),
    ],
)
def test_bad_enum_value_raises(tmp_path: Path, field: str, bad_value: Any) -> None:
    doc = _document()
    doc["metrics"][0][field] = bad_value
    with pytest.raises(OntologyLoadError) as excinfo:
        load_saas_metrics(path=_write(tmp_path, doc))
    message = str(excinfo.value)
    assert field in message
    assert doc["metrics"][0]["id"] in message


@pytest.mark.parametrize("field", ["kind", "value_type", "period_semantics"])
def test_every_declared_member_is_accepted(tmp_path: Path, field: str) -> None:
    """A valid member of the vocabulary must still load for every metric."""
    allowed = {
        "kind": METRIC_KINDS,
        "value_type": VALUE_TYPES,
        "period_semantics": PERIOD_SEMANTICS,
    }[field]
    for member in allowed:
        doc = _document()
        doc["metrics"][0][field] = member
        loaded = load_saas_metrics(path=_write(tmp_path, doc))
        assert getattr(loaded.metrics[0], field) == member


@pytest.mark.parametrize("field", ["aliases", "required_qualifiers", "comparability_key_fields"])
def test_empty_string_list_is_rejected(tmp_path: Path, field: str) -> None:
    """``all([])`` is True, so the old check accepted the empty list it named."""
    doc = _document()
    doc["metrics"][0][field] = []
    with pytest.raises(OntologyLoadError, match="non-empty string list"):
        load_saas_metrics(path=_write(tmp_path, doc))


def test_empty_comparability_key_fields_would_make_everything_comparable(
    tmp_path: Path,
) -> None:
    """The concrete harm behind the empty-list bug, pinned as a regression.

    With an empty key field list ``build_comparability_key`` returns the empty
    string for every metric, so an ARR fact and an RPO fact would compare
    equal. The loader must refuse the document rather than let that reach
    ``validate.pipeline``.
    """
    doc = _document()
    for metric in doc["metrics"]:
        metric["comparability_key_fields"] = []
    with pytest.raises(OntologyLoadError, match="comparability_key_fields"):
        load_saas_metrics(path=_write(tmp_path, doc))


def test_empty_family_metric_ids_is_rejected(tmp_path: Path) -> None:
    doc = _document()
    doc["families"][0]["metric_ids"] = []
    with pytest.raises(OntologyLoadError, match="non-empty string list"):
        load_saas_metrics(path=_write(tmp_path, doc))
