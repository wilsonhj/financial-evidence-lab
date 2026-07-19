"""Concurrent lane fusion, evidence dedupe, RRF and reranker hook (M2-014 / T0205).

This module turns the per-lane candidate lists produced by ``lanes.py`` into a
single, deterministically ordered candidate set with an ordered decision trace
(ADR-0006 §5). The pipeline is:

1. **Concurrent lanes.** ``execute_lanes`` runs each lane call on its own thread
   (DB round-trips release the GIL). Results are collected by lane name and then
   emitted in a *fixed lane order* — never order-of-completion — so concurrency
   never perturbs the fused result. Any lane raising fails the whole fusion
   closed (``LaneExecutionError``); there is no silent partial fusion.
2. **Evidence dedupe** (pre-fusion, ADR-0006 §3). Candidates that resolve to the
   same underlying evidence (same fact / table-row / source-span identity) are
   collapsed to a single survivor before scoring, recording a ``stage='dedupe'``
   decision naming the merged and surviving item ids. Survivor rule is
   deterministic: best (lowest) rank across lane appearances, ties broken by
   ascending item id.
3. **RRF k=60.** Each surviving item scores ``Σ_lanes 1/(60 + lane_rank)``.
   Fused order is RRF descending with an ascending-item-id stable tie-break, and
   every per-lane contribution (lane, rank, raw score, RRF term) stays attached
   for the trace.
4. **Reranker hook.** The top-100 fused candidates are handed to a ``Reranker``
   (``NoopReranker`` by default, returning them unchanged) and a
   ``stage='rerank'`` decision is recorded so the hook is traceable even when it
   is a no-op. The result is then truncated to the plan's ``fused_top_k`` budget.

Determinism: identical lane outputs yield a byte-identical ``FusionResult``
(``to_canonical_json``) regardless of thread completion order or the iteration
order of the supplied lane results. No wall-clock is read inside the fusion
logic; timestamps come from an injected ``now`` callable (or are left ``None``
for the persistence layer to stamp).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from fel_retrieval.lanes import LANE_DENSE, LANE_FACTS, LANE_LEXICAL, LANE_TABLES, LaneCandidate

# Fixed order lanes are fused in. Collection is concurrent, but everything
# downstream iterates lanes in this order so results never depend on which
# thread finished first.
LANE_ORDER: tuple[str, ...] = (LANE_DENSE, LANE_LEXICAL, LANE_FACTS, LANE_TABLES)

# RRF constant (ADR-0006 §5). Kept as a module constant so tests pin the exact
# value and callers cannot drift it.
RRF_K = 60

# The reranker hook always sees the fused top-100 (ADR-0006 §5), independent of
# the (<=100) ``fused_top_k`` the final result is truncated to.
RERANK_TOP_N = 100

# RRF terms are summed as fixed-precision decimals so the fused score is
# order-independent and byte-stable (float addition is neither).
_RRF_QUANT = Decimal("0.000000000001")


class LaneExecutionError(RuntimeError):
    """A lane call failed; fusion fails closed rather than fusing a partial set.

    Carries the offending ``lane`` name and chains the original exception so the
    trace/persistence layer can attribute the failure.
    """

    def __init__(self, lane: str, cause: BaseException) -> None:
        super().__init__(f"lane {lane!r} failed: {cause}")
        self.lane = lane
        self.__cause__ = cause


# A bound, zero-argument lane invocation. Callers typically close over their own
# DB connection so concurrent calls never share a (non-thread-safe) connection.
LaneCall = Callable[[], list[LaneCandidate]]


@dataclass(frozen=True)
class Contribution:
    """One lane's contribution to a fused candidate (CandidateContribution shape).

    ``variant_index`` defaults to 0 — this fusion operates over a single query
    variant; multi-variant timing/expansion is a persistence concern. ``raw_score``
    and ``rrf_contribution`` are fixed-precision decimal strings matching the
    contract's ``^-?[0-9]+(\\.[0-9]+)?$`` pattern.
    """

    lane: str
    lane_rank: int
    raw_score: str
    rrf_contribution: str
    variant_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "variant_index": self.variant_index,
            "lane_rank": self.lane_rank,
            "raw_score": self.raw_score,
            "rrf_contribution": self.rrf_contribution,
        }


@dataclass(frozen=True)
class FusedCandidate:
    """A deduped, RRF-scored candidate with its per-lane contributions.

    Provenance fields are carried through from the surviving ``LaneCandidate`` so
    downstream persistence (M2-015) can express the full ``Candidate`` contract
    without re-reading the DB.
    """

    item_id: str
    kind: str
    contributions: tuple[Contribution, ...]
    fused_score: str
    fused_rank: int
    source_span_id: str
    document_version_id: str
    document_id: str
    published_at: Any
    financial_fact_id: str | None = None
    table_id: str | None = None
    table_row_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "contributions": [c.to_dict() for c in self.contributions],
            "fused_score": self.fused_score,
            "fused_rank": self.fused_rank,
            "source_span_id": self.source_span_id,
            "document_version_id": self.document_version_id,
            "document_id": self.document_id,
            "financial_fact_id": self.financial_fact_id,
            "table_id": self.table_id,
            "table_row_index": self.table_row_index,
        }


@dataclass(frozen=True)
class RetrievalDecision:
    """One trace decision (RetrievalDecision shape).

    ``occurred_at`` is whatever the injected ``now`` callable returned (an
    ISO-8601 string) or ``None`` when the persistence layer will stamp it. It is
    intentionally excluded from ``to_dict`` used for determinism comparison so a
    clock injection cannot make an otherwise-identical fusion diverge.
    """

    stage: str
    code: str
    item_ids: tuple[str, ...]
    detail: dict[str, Any] = field(default_factory=dict)
    occurred_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "code": self.code,
            "item_ids": list(self.item_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FusionResult:
    """Fused candidates (ranked) plus the ordered decision trace."""

    candidates: tuple[FusedCandidate, ...]
    decisions: tuple[RetrievalDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "decisions": [d.to_dict() for d in self.decisions],
        }

    def to_canonical_json(self) -> str:
        """Byte-stable JSON (sorted keys) — the determinism contract."""
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class Reranker(Protocol):
    """Reranks fused candidates. ``name`` labels the recorded rerank decision."""

    name: str

    def rerank(
        self, candidates: Sequence[FusedCandidate], *, top_n: int
    ) -> Sequence[FusedCandidate]: ...


class NoopReranker:
    """Identity reranker: returns its input unchanged (order preserved).

    Ships per ADR-0006 §5 so the reranker seam is exercised and traced before any
    cross-encoder is activated.
    """

    name = "noop"

    def rerank(
        self, candidates: Sequence[FusedCandidate], *, top_n: int
    ) -> Sequence[FusedCandidate]:
        return list(candidates)


# --- Concurrent lane execution --------------------------------------------
def execute_lanes(
    lane_calls: Sequence[tuple[str, LaneCall]],
    *,
    max_workers: int | None = None,
) -> dict[str, list[LaneCandidate]]:
    """Run each ``(lane, call)`` concurrently, collecting results by lane name.

    Threads are used because each lane call is a DB round-trip that releases the
    GIL. Determinism is preserved by returning a plain dict the caller reads in
    ``LANE_ORDER`` — completion order is never observed. The first lane to raise
    fails the whole call closed with a ``LaneExecutionError``; no partial result
    is ever returned.
    """
    if not lane_calls:
        return {}
    workers = max_workers if max_workers is not None else len(lane_calls)
    results: dict[str, list[LaneCandidate]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(call): lane for lane, call in lane_calls}
        for future in futures:
            lane = futures[future]
            try:
                results[lane] = future.result()
            except Exception as exc:  # noqa: BLE001 - re-raised as typed fail-closed
                raise LaneExecutionError(lane, exc) from exc
    return results


# --- Dedupe ----------------------------------------------------------------
def _provenance_key(candidate: LaneCandidate) -> tuple[str, ...]:
    """Identity of the underlying evidence, independent of item id / lane.

    Facts key on their ``financial_fact_id``, table rows on ``(table_id, row)``,
    everything else on the ``source_span_id`` the item anchors to. Two distinct
    retrieval items that resolve to the same evidence collide here and are
    deduped before scoring.
    """
    if candidate.financial_fact_id is not None:
        return ("fact", candidate.financial_fact_id)
    if candidate.table_id is not None:
        return ("table", candidate.table_id, str(candidate.table_row_index))
    return ("span", candidate.source_span_id)


def _best_rank(appearances: Sequence[LaneCandidate]) -> int:
    """Best (lowest) lane rank an item achieved across the lanes it appeared in."""
    return min(app.lane_rank for app in appearances)


def _dedupe(
    by_item: Mapping[str, list[LaneCandidate]],
) -> tuple[dict[str, list[LaneCandidate]], list[RetrievalDecision]]:
    """Collapse items sharing provenance to one survivor; record dedupe decisions.

    ``by_item`` maps item id -> its lane appearances (already grouped). Returns
    the surviving subset (same shape) and one ``stage='dedupe'`` decision per
    group that actually collapsed (>1 item id). Survivor = best rank, ties broken
    by ascending item id.
    """
    groups: dict[tuple[str, ...], list[str]] = {}
    for item_id, appearances in by_item.items():
        groups.setdefault(_provenance_key(appearances[0]), []).append(item_id)

    survivors: dict[str, list[LaneCandidate]] = {}
    decisions: list[RetrievalDecision] = []
    for key in sorted(groups):
        item_ids = groups[key]
        # Deterministic survivor: lowest best-rank, then lowest item id.
        winner = min(item_ids, key=lambda iid: (_best_rank(by_item[iid]), iid))
        survivors[winner] = by_item[winner]
        if len(item_ids) > 1:
            merged = sorted(iid for iid in item_ids if iid != winner)
            decisions.append(
                RetrievalDecision(
                    stage="dedupe",
                    code="provenance_merge",
                    item_ids=tuple(sorted(item_ids)),
                    detail={
                        "provenance": list(key),
                        "survivor": winner,
                        "merged": merged,
                    },
                )
            )
    return survivors, decisions


# --- RRF fusion ------------------------------------------------------------
def _rrf_term(lane_rank: int) -> Decimal:
    return (Decimal(1) / Decimal(RRF_K + lane_rank)).quantize(_RRF_QUANT)


def _fuse_survivors(
    survivors: Mapping[str, list[LaneCandidate]],
) -> list[FusedCandidate]:
    """Score each survivor with RRF k=60 and order RRF-desc, item-id-asc.

    Contributions are attached in ``LANE_ORDER`` so the candidate is byte-stable
    regardless of the order lanes were collected in.
    """
    lane_priority = {lane: i for i, lane in enumerate(LANE_ORDER)}
    scored: list[tuple[Decimal, str, FusedCandidate]] = []
    for item_id, appearances in survivors.items():
        ordered = sorted(
            appearances,
            key=lambda app: (lane_priority.get(app.lane, len(LANE_ORDER)), app.lane_rank),
        )
        total = Decimal(0)
        contributions: list[Contribution] = []
        for app in ordered:
            term = _rrf_term(app.lane_rank)
            total += term
            contributions.append(
                Contribution(
                    lane=app.lane,
                    lane_rank=app.lane_rank,
                    raw_score=app.raw_score,
                    rrf_contribution=f"{term:f}",
                )
            )
        representative = ordered[0]
        fused = FusedCandidate(
            item_id=item_id,
            kind=representative.kind,
            contributions=tuple(contributions),
            fused_score=f"{total:f}",
            fused_rank=0,  # assigned after ordering below
            source_span_id=representative.source_span_id,
            document_version_id=representative.document_version_id,
            document_id=representative.document_id,
            published_at=representative.published_at,
            financial_fact_id=representative.financial_fact_id,
            table_id=representative.table_id,
            table_row_index=representative.table_row_index,
        )
        scored.append((total, item_id, fused))

    # RRF descending; ascending item id is the stable tie-break.
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    ranked: list[FusedCandidate] = []
    for rank, (_total, _item_id, fused) in enumerate(scored, start=1):
        ranked.append(_with_rank(fused, rank))
    return ranked


def _with_rank(candidate: FusedCandidate, rank: int) -> FusedCandidate:
    return FusedCandidate(
        item_id=candidate.item_id,
        kind=candidate.kind,
        contributions=candidate.contributions,
        fused_score=candidate.fused_score,
        fused_rank=rank,
        source_span_id=candidate.source_span_id,
        document_version_id=candidate.document_version_id,
        document_id=candidate.document_id,
        published_at=candidate.published_at,
        financial_fact_id=candidate.financial_fact_id,
        table_id=candidate.table_id,
        table_row_index=candidate.table_row_index,
    )


def _group_by_item(
    lane_results: Mapping[str, list[LaneCandidate]],
) -> dict[str, list[LaneCandidate]]:
    """Group every lane hit by item id, iterating lanes in fixed order.

    Lanes absent from ``lane_results`` are skipped; unexpected lane names are
    appended after the known ones so nothing is silently dropped.
    """
    known = [lane for lane in LANE_ORDER if lane in lane_results]
    extra = sorted(lane for lane in lane_results if lane not in LANE_ORDER)
    by_item: dict[str, list[LaneCandidate]] = {}
    for lane in [*known, *extra]:
        for candidate in lane_results[lane]:
            by_item.setdefault(candidate.item_id, []).append(candidate)
    return by_item


# --- Top-level fusion ------------------------------------------------------
def fuse(
    lane_results: Mapping[str, list[LaneCandidate]],
    *,
    fused_top_k: int,
    reranker: Reranker | None = None,
    now: Callable[[], str] | None = None,
) -> FusionResult:
    """Dedupe, RRF-fuse, rerank-hook and truncate ``lane_results``.

    ``fused_top_k`` is the plan budget the final candidate list is truncated to
    (after the reranker sees the top-100). ``reranker`` defaults to
    ``NoopReranker``. ``now`` optionally stamps each decision's ``occurred_at``;
    when ``None`` the persistence layer stamps them. The result is deterministic
    for any iteration order of ``lane_results``.
    """
    if fused_top_k < 0:
        raise ValueError("fused_top_k must be non-negative")
    active_reranker: Reranker = reranker if reranker is not None else NoopReranker()

    by_item = _group_by_item(lane_results)
    survivors, dedupe_decisions = _dedupe(by_item)
    fused = _fuse_survivors(survivors)

    decisions: list[RetrievalDecision] = list(dedupe_decisions)
    decisions.append(
        RetrievalDecision(
            stage="fusion",
            code="rrf_k60",
            item_ids=tuple(c.item_id for c in fused),
            detail={"k": RRF_K, "fused_count": len(fused)},
        )
    )

    # Reranker hook over the fused top-100; recorded even for the no-op.
    hook_input = fused[:RERANK_TOP_N]
    reranked = list(active_reranker.rerank(hook_input, top_n=RERANK_TOP_N))
    decisions.append(
        RetrievalDecision(
            stage="rerank",
            code=active_reranker.name,
            item_ids=tuple(c.item_id for c in hook_input),
            detail={"top_n": RERANK_TOP_N, "reranker": active_reranker.name},
        )
    )

    # A no-op rerank leaves fused order intact; a real reranker's output order is
    # honored while the tail beyond top-100 keeps its fused order.
    final = [*reranked, *fused[RERANK_TOP_N:]][:fused_top_k]

    if now is not None:
        stamp = now()
        decisions = [
            RetrievalDecision(
                stage=d.stage,
                code=d.code,
                item_ids=d.item_ids,
                detail=d.detail,
                occurred_at=stamp,
            )
            for d in decisions
        ]

    return FusionResult(candidates=tuple(final), decisions=tuple(decisions))


__all__ = [
    "LANE_ORDER",
    "RERANK_TOP_N",
    "RRF_K",
    "Contribution",
    "FusedCandidate",
    "FusionResult",
    "LaneCall",
    "LaneExecutionError",
    "NoopReranker",
    "Reranker",
    "RetrievalDecision",
    "execute_lanes",
    "fuse",
]
