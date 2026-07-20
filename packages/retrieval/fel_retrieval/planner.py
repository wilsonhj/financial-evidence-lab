"""Typed deterministic query planner (M2-013 / T0204, ADR-0006 §5).

``plan_query`` is a pure function: no DB, no randomness, no clock. Identical
inputs serialize to byte-identical ``query-plan/v1`` documents. Rule-based
intent classification, a frozen financial synonym table (max four variants),
fail-closed filter validation and deterministic budget derivation mirror the
frozen ``QueryPlan`` contract in ``packages/contracts/schemas/query-plan.schema.json``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

SCHEMA_VERSION = "query-plan/v1"

MIN_TOP_K = 1
MAX_TOP_K = 100
DEFAULT_TOP_K = 100

MAX_CONTEXT_ITEMS = 16
DEFAULT_TIMEOUT_MS = 15000

MAX_VARIANTS = 4
MAX_FILTER_ITEMS = 20

DEFAULT_LANES: tuple[str, ...] = ("dense", "lexical", "facts", "tables")
VALID_LANES: frozenset[str] = frozenset(DEFAULT_LANES)

DEFAULT_INTENT = "general"


class PlannerValidationError(ValueError):
    """Fail-closed planner rejection carrying a stable ``code`` and ``field``."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.field = field


@dataclass(frozen=True)
class QueryRequest:
    """User-supplied ``CreateQuery`` inputs relevant to planning."""

    question: str
    lanes: tuple[str, ...] | None = None
    top_k: int | None = None
    forms: tuple[str, ...] | None = None
    periods: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PlanFilters:
    forms: tuple[str, ...] = ()
    periods: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if self.forms:
            out["forms"] = list(self.forms)
        if self.periods:
            out["periods"] = list(self.periods)
        return out


@dataclass(frozen=True)
class PlanBudgets:
    lane_top_k: int
    fused_top_k: int
    context_items: int
    timeout_ms: int

    def to_dict(self) -> dict[str, int]:
        return {
            "lane_top_k": self.lane_top_k,
            "fused_top_k": self.fused_top_k,
            "context_items": self.context_items,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True)
class QueryPlan:
    """Immutable ``query-plan/v1`` document with stable serialization."""

    schema_version: str
    intent: str
    entity_ids: tuple[str, ...]
    effective_as_of: str
    corpus_version_id: str
    index_version_id: str
    lanes: tuple[str, ...]
    variants: tuple[str, ...]
    filters: PlanFilters
    budgets: PlanBudgets

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent": self.intent,
            "entity_ids": list(self.entity_ids),
            "effective_as_of": self.effective_as_of,
            "corpus_version_id": self.corpus_version_id,
            "index_version_id": self.index_version_id,
            "lanes": list(self.lanes),
            "variants": list(self.variants),
            "filters": self.filters.to_dict(),
            "budgets": self.budgets.to_dict(),
        }

    def to_canonical_json(self) -> str:
        """Byte-stable JSON (sorted keys) — the determinism contract."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# --- Intent classification -------------------------------------------------
# Ordered rules; first match wins so classification is deterministic. Terms are
# matched on word boundaries (see ``_compile_terms``) to avoid partial hits.
_INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "contradiction",
        ("contradict", "contradiction", "inconsistent", "discrepancy", "conflict", "disagree"),
    ),
    (
        "driver_analysis",
        (
            "why",
            "driver",
            "drivers",
            "driven by",
            "because",
            "reason for",
            "contributed to",
            "attributable to",
        ),
    ),
    (
        "comparison",
        (
            "compare",
            "comparison",
            "versus",
            "vs",
            "year over year",
            "year-over-year",
            "yoy",
            "relative to",
            "change from",
        ),
    ),
    ("guidance", ("guidance", "outlook", "forecast", "guide")),
    ("table_reasoning", ("table", "breakdown", "line item", "sum of", "total across")),
    ("section_lookup", ("section", "item 7", "md&a", "risk factors", "notes to")),
    ("fact_lookup", ("what was", "how much", "what is the", "value of", "amount of", "report")),
)


def _compile_terms(terms: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(
        re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE) for term in terms
    )


_INTENT_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (intent, _compile_terms(terms)) for intent, terms in _INTENT_RULES
)


def classify_intent(question: str) -> str:
    """Deterministic rule-based intent; unknown falls back to ``general``."""
    for intent, patterns in _INTENT_PATTERNS:
        if any(pattern.search(question) for pattern in patterns):
            return intent
    return DEFAULT_INTENT


# --- Synonym expansion -----------------------------------------------------
# Curated financial-domain synonyms. Order is fixed so variant generation is
# deterministic. Keys are matched case-insensitively on word boundaries and the
# first occurrence is substituted, producing up to ``MAX_VARIANTS`` total.
_SYNONYMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("net income", ("net earnings", "profit", "bottom line")),
    ("gross margin", ("gross profit margin",)),
    ("free cash flow", ("fcf",)),
    ("operating expenses", ("opex",)),
    ("cost of goods sold", ("cogs", "cost of revenue")),
    ("capital expenditures", ("capex",)),
    ("revenue", ("net sales", "total revenue", "sales")),
    ("cogs", ("cost of goods sold", "cost of revenue")),
    ("capex", ("capital expenditures",)),
    ("opex", ("operating expenses",)),
    ("fcf", ("free cash flow",)),
    ("eps", ("earnings per share",)),
    ("guidance", ("outlook", "forecast")),
)

_SYNONYM_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)", re.IGNORECASE), syns)
    for key, syns in _SYNONYMS
)


def expand_variants(question: str) -> tuple[str, ...]:
    """Original plus deduped synonym rewrites, capped at ``MAX_VARIANTS``."""
    variants: list[str] = [question]
    seen: set[str] = {question}
    for pattern, syns in _SYNONYM_PATTERNS:
        if pattern.search(question) is None:
            continue
        for syn in syns:
            # Synonyms are literal (no backslashes/group refs), so plain sub is safe.
            variant = pattern.sub(syn, question, count=1)
            if variant in seen:
                continue
            variants.append(variant)
            seen.add(variant)
            if len(variants) >= MAX_VARIANTS:
                return tuple(variants)
    return tuple(variants)


# --- Budgets ---------------------------------------------------------------
def derive_budgets(top_k: int) -> PlanBudgets:
    """Deterministic budgets from ``top_k`` within schema bounds (ADR-0006 §5)."""
    context_items = max(1, min(top_k, MAX_CONTEXT_ITEMS))
    return PlanBudgets(
        lane_top_k=top_k,
        fused_top_k=top_k,
        context_items=context_items,
        timeout_ms=DEFAULT_TIMEOUT_MS,
    )


# --- Filter / pin validation ----------------------------------------------
_PERIOD_RE = re.compile(r"^\d{4}(-Q[1-4]|-H[1-2]|-(0[1-9]|1[0-2]))?$")


def _require_uuid(value: str, field: str) -> None:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise PlannerValidationError("INVALID_UUID", field, f"{field} must be a UUID") from exc


def _require_datetime(value: str, field: str) -> None:
    text = value[:-1] + "+00:00" if isinstance(value, str) and value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
    except (ValueError, AttributeError, TypeError) as exc:
        raise PlannerValidationError(
            "INVALID_AS_OF", field, f"{field} must be an ISO-8601 date-time"
        ) from exc


def _resolve_top_k(top_k: int | None) -> int:
    if top_k is None:
        return DEFAULT_TOP_K
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise PlannerValidationError("TOP_K_NOT_INTEGER", "top_k", "top_k must be an integer")
    if not MIN_TOP_K <= top_k <= MAX_TOP_K:
        raise PlannerValidationError(
            "TOP_K_OUT_OF_RANGE", "top_k", f"top_k must be in [{MIN_TOP_K}, {MAX_TOP_K}]"
        )
    return top_k


def _resolve_lanes(lanes: tuple[str, ...] | None) -> tuple[str, ...]:
    if lanes is None:
        return DEFAULT_LANES
    if len(lanes) == 0:
        raise PlannerValidationError("EMPTY_LANES", "lanes", "lanes must not be empty")
    if len(lanes) > len(DEFAULT_LANES):
        raise PlannerValidationError(
            "TOO_MANY_LANES", "lanes", f"at most {len(DEFAULT_LANES)} lanes"
        )
    seen: set[str] = set()
    for lane in lanes:
        if lane not in VALID_LANES:
            raise PlannerValidationError("UNKNOWN_LANE", "lanes", f"unknown lane {lane!r}")
        if lane in seen:
            raise PlannerValidationError("DUPLICATE_LANE", "lanes", f"duplicate lane {lane!r}")
        seen.add(lane)
    return tuple(lanes)


def _resolve_filters(forms: tuple[str, ...] | None, periods: tuple[str, ...] | None) -> PlanFilters:
    if forms is not None:
        if len(forms) > MAX_FILTER_ITEMS:
            raise PlannerValidationError(
                "TOO_MANY_FORMS", "forms", f"at most {MAX_FILTER_ITEMS} forms"
            )
        for form in forms:
            if not form or not form.strip():
                raise PlannerValidationError("EMPTY_FORM", "forms", "form values must be non-empty")
    if periods is not None:
        if len(periods) > MAX_FILTER_ITEMS:
            raise PlannerValidationError(
                "TOO_MANY_PERIODS", "periods", f"at most {MAX_FILTER_ITEMS} periods"
            )
        for period in periods:
            if _PERIOD_RE.match(period) is None:
                raise PlannerValidationError(
                    "INVALID_PERIOD", "periods", f"unparsable period {period!r}"
                )
    return PlanFilters(forms=tuple(forms or ()), periods=tuple(periods or ()))


def plan_query(
    request: QueryRequest,
    *,
    index_version_id: str,
    corpus_version_id: str,
    entity_ids: Sequence[str],
    effective_as_of: str,
) -> QueryPlan:
    """Build an immutable ``query-plan/v1`` from a request and resolved pins.

    The resolved pins (``index_version_id``, ``corpus_version_id``,
    ``entity_ids``, ``effective_as_of``) are captured by the caller at plan time;
    the planner validates and pins them but never resolves them from a DB or
    clock, keeping the function pure and reproducible.
    """
    if not request.question or not request.question.strip():
        raise PlannerValidationError("EMPTY_QUESTION", "question", "question must not be empty")
    if len(request.question) > 4000:
        raise PlannerValidationError(
            "QUESTION_TOO_LONG", "question", "question must be at most 4000 characters"
        )

    top_k = _resolve_top_k(request.top_k)
    lanes = _resolve_lanes(request.lanes)
    filters = _resolve_filters(request.forms, request.periods)

    if len(entity_ids) == 0:
        raise PlannerValidationError(
            "NO_ENTITY_IDS", "entity_ids", "at least one entity_id is required"
        )
    for entity_id in entity_ids:
        _require_uuid(entity_id, "entity_ids")
    _require_uuid(index_version_id, "index_version_id")
    _require_uuid(corpus_version_id, "corpus_version_id")
    _require_datetime(effective_as_of, "effective_as_of")

    return QueryPlan(
        schema_version=SCHEMA_VERSION,
        intent=classify_intent(request.question),
        entity_ids=tuple(entity_ids),
        effective_as_of=effective_as_of,
        corpus_version_id=corpus_version_id,
        index_version_id=index_version_id,
        lanes=lanes,
        variants=expand_variants(request.question),
        filters=filters,
        budgets=derive_budgets(top_k),
    )
