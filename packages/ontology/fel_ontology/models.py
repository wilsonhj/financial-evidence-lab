"""Typed ontology models for saas-metrics/v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ValueType = Literal["currency", "currency_derived", "ratio_pct", "count"]
PeriodSemantics = Literal["instant", "duration", "trailing_window"]
MetricKind = Literal[
    "point_in_time_snapshot",
    "ratio",
    "flow",
    "balance",
    "derived",
]


@dataclass(frozen=True, slots=True)
class Family:
    id: str
    name: str
    metric_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricDef:
    id: str
    canonical_name: str
    family_id: str
    kind: MetricKind
    value_type: ValueType
    unit: str
    period_semantics: PeriodSemantics
    scale_handling: str
    aliases: tuple[str, ...]
    required_qualifiers: tuple[str, ...]
    comparability_key_fields: tuple[str, ...]
    derivation_policy: str
    review_policy: str
    notes: str = ""


@dataclass(frozen=True, slots=True)
class OntologyDocument:
    schema_version: str
    ontology_id: str
    limitations: tuple[str, ...]
    families: tuple[Family, ...]
    metrics: tuple[MetricDef, ...]
    content_hash: str

    def metric(self, metric_id: str) -> MetricDef:
        for m in self.metrics:
            if m.id == metric_id:
                return m
        raise KeyError(metric_id)

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return tuple(m.id for m in self.metrics)
