"""Immutable explicit fixed-point policy and nonrecursive execution provenance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from fel_calculation_engine.canonical import canonical_json, content_hash
from fel_calculation_engine.errors import CalculationEngineError, IterationPolicyError
from fel_calculation_engine.periods import FiscalPeriod
from fel_calculation_engine.values import Quantity, require_decimal, require_safe_id

MAX_ITERATIONS = 1000
ITERATION_ALGORITHM = "jacobi/v1"


def _tolerance(value: Decimal, field: str) -> None:
    try:
        require_decimal(value, field)
        canonical_json(value)  # Includes the canonical exponent bound.
    except CalculationEngineError as exc:
        raise IterationPolicyError(exc.message, field=field) from exc
    if value < 0:
        raise IterationPolicyError(f"{field} must be nonnegative", field=field)


@dataclass(frozen=True, slots=True)
class IterationGroup:
    """All algorithm inputs are explicit. Pair tuples keep the policy deeply immutable."""

    group_id: str
    members: tuple[str, ...]
    seeds: tuple[tuple[str, str], ...]
    absolute_tolerances: tuple[tuple[str, Decimal], ...]
    relative_tolerance: Decimal
    max_iterations: int

    def __post_init__(self) -> None:
        require_safe_id(self.group_id, "group_id", IterationPolicyError)
        if not isinstance(self.members, tuple) or not self.members:
            raise IterationPolicyError("members must be a nonempty tuple")
        for member in self.members:
            require_safe_id(member, "member", IterationPolicyError)
        if tuple(sorted(set(self.members))) != self.members:
            raise IterationPolicyError("members must be sorted and unique")
        for name, pairs in (
            ("seeds", self.seeds),
            ("absolute_tolerances", self.absolute_tolerances),
        ):
            if not isinstance(pairs, tuple) or any(
                not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs
            ):
                raise IterationPolicyError(f"{name} must be immutable key/value pairs")
            if tuple(key for key, _ in pairs) != self.members:
                raise IterationPolicyError(f"{name} must declare every member exactly once")
        for _, seed in self.seeds:
            require_safe_id(seed, "seed", IterationPolicyError)
        _tolerance(self.relative_tolerance, "relative_tolerance")
        for member, tolerance in self.absolute_tolerances:
            _tolerance(tolerance, f"{member}.absolute_tolerance")
            if tolerance == 0 and self.relative_tolerance == 0:
                raise IterationPolicyError(f"{member} must have a positive tolerance")
        if type(self.max_iterations) is not int or not 1 <= self.max_iterations <= MAX_ITERATIONS:
            raise IterationPolicyError("max_iterations must be an integer from 1 through 1000")

    @classmethod
    def of(
        cls,
        *,
        group_id: str,
        members: tuple[str, ...],
        seeds: Mapping[str, str],
        absolute_tolerances: Mapping[str, Decimal],
        relative_tolerance: Decimal,
        max_iterations: int,
    ) -> IterationGroup:
        if (
            not isinstance(members, tuple)
            or not isinstance(seeds, Mapping)
            or not isinstance(absolute_tolerances, Mapping)
        ):
            raise IterationPolicyError(
                "members must be a tuple; seeds and tolerances must be mappings"
            )
        for member in (*members, *seeds, *absolute_tolerances):
            require_safe_id(member, "member", IterationPolicyError)
        return cls(
            group_id,
            tuple(sorted(members)),
            tuple(sorted(seeds.items())),
            tuple(sorted(absolute_tolerances.items())),
            relative_tolerance,
            max_iterations,
        )


@dataclass(frozen=True, slots=True)
class IterationRun:
    """Execution DAG evidence; internal equation edges remain node IDs in definitions."""

    schema: ClassVar[str] = "fel-calc-iteration/v1"
    algorithm: ClassVar[str] = ITERATION_ALGORITHM

    run_id: str
    policy: IterationGroup
    member_definitions: tuple[tuple[str, str], ...]
    dependencies: tuple[tuple[str, tuple[str, ...]], ...]
    seed_result_ids: tuple[tuple[str, str, str], ...]
    external_result_ids: tuple[tuple[str, str], ...]
    cutoff: datetime
    iterations: int
    values: tuple[tuple[str, Quantity, FiscalPeriod], ...]
    residuals: tuple[tuple[str, Decimal], ...]

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "algorithm": self.algorithm,
            **{
                field.name: getattr(self, field.name)
                for field in fields(self)
                if field.name != "run_id"
            },
        }

    def verify(self) -> bool:
        return content_hash(self.payload()) == self.run_id
