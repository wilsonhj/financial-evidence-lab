"""Seeded deterministic generators for property tests (T0409).

``hypothesis`` is not available in the repository toolchain and adding a
dependency is outside this package's authorization, so properties are checked
over ``random.Random(seed)`` streams: every failure is reproducible from the
seed printed in the assertion message.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from decimal import Decimal
from random import Random

from fel_calculation_engine.nodes import Node, Operator
from fel_calculation_engine.periods import FiscalQuarter, FiscalYear, PeriodKind
from fel_calculation_engine.units import COUNT, PERCENT, RATIO, Unit, UnitKind, currency

CURRENCIES = ("USD", "EUR", "JPY", "GBP", "KWD")


def cases(count: int = 200, *, base_seed: int = 63) -> Iterator[tuple[int, Random]]:
    for i in range(count):
        seed = base_seed * 1_000 + i
        yield seed, Random(seed)


def decimal(rng: Random, *, digits: int = 12, places: int = 6) -> Decimal:
    """Draw a Decimal with at most ``digits`` significant digits.

    KNOWN LIMIT, recorded rather than papered over: 12 digits never reaches the
    region where precision bites. The ``canonical_decimal`` injectivity defect
    (PR #212 review, finding 1) lived at 29-34 digits, above the ambient
    context's default 28, and this suite structurally could not have found it —
    seven mutations were killed and that one was unreachable. An explicit
    boundary test now covers it (``test_canonical.py``).

    Widening this generator is worth doing and is not a one-liner: properties
    that multiply or quantize need their own headroom, so the bound has to be
    per-property rather than global. Filed as follow-up work.
    """
    magnitude = rng.randint(0, 10**digits - 1)
    exponent = rng.randint(0, places)
    sign = "-" if rng.random() < 0.3 else ""
    return Decimal(f"{sign}{magnitude}E-{exponent}")


def nonzero_decimal(rng: Random, **kwargs: int) -> Decimal:
    while True:
        value = decimal(rng, **kwargs)
        if value != 0:
            return value


def unit(rng: Random, *, allow_percent: bool = True, allow_rate: bool = True) -> Unit:
    kinds = [UnitKind.CURRENCY, UnitKind.COUNT, UnitKind.RATIO]
    if allow_percent:
        kinds.append(UnitKind.PERCENT)
    kind = rng.choice(kinds)
    base = currency(rng.choice(CURRENCIES)) if kind is UnitKind.CURRENCY else Unit(kind=kind)
    if allow_rate and rng.random() < 0.3:
        return base.per(rng.choice(list(PeriodKind)))
    return base


def quarter(rng: Random) -> FiscalQuarter:
    return FiscalQuarter(rng.randint(1990, 2090), rng.randint(1, 4))


def year(rng: Random) -> FiscalYear:
    return FiscalYear(rng.randint(1990, 2090))


def dag(
    rng: Random,
    *,
    size: int,
    source: Callable[[str, str], Node],
    formula: Callable[[str, Operator, tuple[str, ...]], Node],
) -> list[Node]:
    """A random acyclic USD-only graph: ADD/SUB formulas over earlier nodes."""
    leaves = max(2, size // 3)
    nodes: list[Node] = [
        source(f"s{i}", str(decimal(rng, digits=6, places=2))) for i in range(leaves)
    ]
    for i in range(leaves, size):
        pool = [n.node_id for n in nodes]
        if rng.random() < 0.3:
            operands = tuple(rng.sample(pool, 2))
            nodes.append(formula(f"f{i}", Operator.SUB, operands))
        else:
            arity = rng.randint(2, min(4, len(pool)))
            nodes.append(formula(f"f{i}", Operator.ADD, tuple(rng.sample(pool, arity))))
    return nodes


__all__ = [
    "COUNT",
    "CURRENCIES",
    "PERCENT",
    "RATIO",
    "cases",
    "dag",
    "decimal",
    "nonzero_decimal",
    "quarter",
    "unit",
    "year",
]
