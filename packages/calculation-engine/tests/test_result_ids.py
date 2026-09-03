"""Content-addressed result ids and adversarial collision tests (T0403, issue #63 checklist)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, timedelta, timezone
from decimal import Decimal

from _fixtures import AS_OF, CUTOFF, Q1, USD, assumption, formula, revenue_model, source

from fel_calculation_engine.engine import evaluate
from fel_calculation_engine.nodes import Operator
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.units import COUNT, RATIO, Unit, UnitKind


def _ids(nodes: list, cutoff=CUTOFF) -> dict[str, str]:  # type: ignore[no-untyped-def,type-arg]
    return {
        k: r.result_id
        for k, r in evaluate(GraphSnapshot.build("m", nodes), cutoff=cutoff).results.items()
    }


def test_result_ids_are_sha256_content_hashes_stable_across_node_order() -> None:
    nodes = revenue_model()
    a = _ids(nodes)
    b = _ids(list(reversed(nodes)))
    assert a == b
    assert all(v.startswith("sha256:") and len(v) == 71 for v in a.values())
    assert len(set(a.values())) == len(a)


def test_value_change_anywhere_upstream_changes_every_downstream_id_only() -> None:
    base = _ids(revenue_model())
    changed = revenue_model()
    changed[4] = assumption("growth", "0.11")
    new = _ids(changed)
    assert new["growth"] != base["growth"]
    assert new["growth-factor"] != base["growth-factor"]
    assert new["revenue-next"] != base["revenue-next"]
    for untouched in ("price", "units-fact", "units", "revenue", "one", "reported-revenue"):
        assert new[untouched] == base[untouched]


def test_one_ulp_value_change_and_rescaling_behave_as_documented() -> None:
    assert _ids([source("a", "1.000000")])["a"] == _ids([source("a", "1")])["a"]
    assert _ids([source("a", "1.000001")])["a"] != _ids([source("a", "1")])["a"]
    assert _ids([source("a", "-0")])["a"] == _ids([source("a", "0")])["a"]


def test_delimiter_forgery_in_ids_cannot_collide() -> None:
    a = _ids([source("a", "1", span="x.y"), source("b", "1", span="z")])
    b = _ids([source("a", "1", span="x"), source("b", "1", span="y.z")])
    assert a["a"] != b["a"] and a["b"] != b["b"]
    left = _ids([source("ab", "1", span="s"), source("c", "1", span="s")])
    right = _ids([source("a", "1", span="s"), source("bc", "1", span="s")])
    assert set(left.values()).isdisjoint(right.values())


def test_none_versus_sentinel_unit_axes_cannot_collide() -> None:
    plain = _ids([source("a", "1", unit=COUNT)])["a"]
    # No sentinel string can stand in for an absent currency: currency codes are validated,
    # and the canonical encoding writes null rather than "-", "None" or "".
    for forged in ("XXX", "NON", "NUL"):
        assert (
            _ids([source("a", "1", unit=Unit(kind=UnitKind.CURRENCY, currency=forged))])["a"]
            != plain
        )


def test_operand_order_and_operator_are_part_of_identity() -> None:
    sub_ab = _ids([source("a", "3"), source("b", "1"), formula("f", Operator.SUB, ("a", "b"))])["f"]
    sub_ba = _ids([source("a", "3"), source("b", "1"), formula("f", Operator.SUB, ("b", "a"))])["f"]
    div_ab = _ids(
        [source("a", "3"), source("b", "1"), formula("f", Operator.DIV, ("a", "b"), unit=RATIO)]
    )["f"]
    assert len({sub_ab, sub_ba, div_ab}) == 3
    v1 = _ids(
        [source("a", "3"), source("b", "1"), formula("f", Operator.ADD, ("a", "b"), version="v1")]
    )["f"]
    v2 = _ids(
        [source("a", "3"), source("b", "1"), formula("f", Operator.ADD, ("a", "b"), version="v2")]
    )["f"]
    assert v1 != v2


def test_timezone_equivalent_as_of_and_cutoff_share_an_identity() -> None:
    plus_two = AS_OF.astimezone(timezone(timedelta(hours=2)))
    assert _ids([source("a", "1", as_of=plus_two)]) == _ids([source("a", "1", as_of=AS_OF)])
    assert _ids(
        [source("a", "1")], cutoff=CUTOFF.astimezone(timezone(timedelta(hours=-5)))
    ) == _ids([source("a", "1")])
    assert _ids([source("a", "1")], cutoff=CUTOFF + timedelta(days=1)) != _ids([source("a", "1")])


def test_label_is_presentation_and_not_part_of_result_identity() -> None:
    node = source("a", "1")
    relabelled = dataclasses.replace(node, label="Revenue (restated)")
    assert _ids([node]) == _ids([relabelled])
    assert (
        GraphSnapshot.build("m", [node]).snapshot_id
        != GraphSnapshot.build("m", [relabelled]).snapshot_id
    )


def test_type_confusion_between_string_and_decimal_cannot_collide() -> None:
    from fel_calculation_engine.canonical import content_hash

    assert content_hash({"value": Decimal("1")}) != content_hash({"value": "1"})
    assert content_hash({"value": Decimal("1")}) != content_hash({"value": 1})
    assert content_hash({"period": Q1}) != content_hash({"period": "FY2024Q1"})
    assert content_hash({"unit": USD}) != content_hash({"unit": "currency:USD"})
    assert content_hash({"as_of": AS_OF}) != content_hash(
        {"as_of": AS_OF.astimezone(UTC).isoformat()}
    )
