import type {
  Candidate,
  CandidateContribution,
  QueryPlan,
  RetrievalClaim,
  RetrievalDecision,
  RetrievalTrace,
} from "./query-source";

export const LANES = ["dense", "lexical", "facts", "tables"] as const;
export type Lane = (typeof LANES)[number];

/**
 * Independent client-side integrity guard. A candidate may be shown as
 * supported/context evidence ONLY when the server accepted it AND it is not
 * published after the run's effective cutoff. Trusting `accepted` alone is not
 * enough: a future-dated or cross-version item that slips through with
 * accepted=true must still never render as supported. Reclassification here is
 * the last line of defence behind server filtering.
 */
export function isRenderableAsSupported(candidate: Candidate, plan: QueryPlan): boolean {
  if (!candidate.accepted) return false;
  return Date.parse(candidate.published_at) <= Date.parse(plan.effective_as_of);
}

export interface RejectedCandidate {
  candidate: Candidate;
  /** Reason code shown to the user; synthesised when the server accepted a future item. */
  code: string;
}

/**
 * Splits candidates into the supported context set and the rejected set. A
 * candidate the server accepted but that fails the temporal guard is moved to
 * rejected with a synthesised `temporal_after_cutoff` code, never supported.
 */
export function partitionCandidates(trace: RetrievalTrace): {
  supported: Candidate[];
  rejected: RejectedCandidate[];
} {
  const supported: Candidate[] = [];
  const rejected: RejectedCandidate[] = [];
  for (const candidate of trace.candidates) {
    if (isRenderableAsSupported(candidate, trace.plan)) {
      supported.push(candidate);
    } else if (candidate.accepted) {
      // Accepted by the server but fails the client temporal guard.
      rejected.push({ candidate, code: "temporal_after_cutoff" });
    } else {
      rejected.push({ candidate, code: candidate.rejection_code ?? "rejected" });
    }
  }
  return { supported, rejected };
}

export interface LaneCandidateRow {
  candidate: Candidate;
  contribution: CandidateContribution;
  fusedRank: number | null;
  fusedScore: string;
  rerankRank: number | null;
  rerankScore: string | null;
  supported: boolean;
}

/** Per-lane candidate rows ordered by the lane's raw rank, with fused/rerank ranks. */
export function laneColumns(trace: RetrievalTrace): Record<Lane, LaneCandidateRow[]> {
  const columns = Object.fromEntries(
    LANES.map((lane) => [lane, [] as LaneCandidateRow[]]),
  ) as Record<Lane, LaneCandidateRow[]>;
  for (const candidate of trace.candidates) {
    const supported = isRenderableAsSupported(candidate, trace.plan);
    for (const contribution of candidate.contributions) {
      columns[contribution.lane].push({
        candidate,
        contribution,
        fusedRank: candidate.fused_rank ?? null,
        fusedScore: candidate.fused_score,
        rerankRank: candidate.rerank_rank ?? null,
        rerankScore: candidate.rerank_score ?? null,
        supported,
      });
    }
  }
  for (const lane of LANES) {
    columns[lane].sort((a, b) => a.contribution.lane_rank - b.contribution.lane_rank);
  }
  return columns;
}

export type ClaimDisplayStatus = RetrievalClaim["status"] | "unverifiable";

export interface ClaimView {
  claim: RetrievalClaim;
  /**
   * Status actually shown. A "supported" claim whose citations reference a
   * non-supported (future/cross-version/rejected) item is downgraded to
   * "unverifiable" so unsupported evidence can never masquerade as supported.
   */
  displayStatus: ClaimDisplayStatus;
  downgraded: boolean;
}

export function claimViews(trace: RetrievalTrace): ClaimView[] {
  const supportedItemIds = new Set(partitionCandidates(trace).supported.map((c) => c.item_id));
  return trace.claims.map((claim) => {
    const citesUnsupported = claim.citations.some((c) => !supportedItemIds.has(c.item_id));
    const downgraded =
      (claim.status === "supported" || claim.status === "partially_supported") && citesUnsupported;
    return {
      claim,
      displayStatus: downgraded ? "unverifiable" : claim.status,
      downgraded,
    };
  });
}

export interface TimelineEntry {
  stage: RetrievalDecision["stage"];
  code: string;
  itemIds: string[];
  detail?: Record<string, unknown>;
  occurredAt: string;
}

/** Ordered dedupe/rejection/decision timeline from the trace decisions. */
export function decisionTimeline(trace: RetrievalTrace): TimelineEntry[] {
  return [...trace.decisions]
    .map((decision) => ({
      stage: decision.stage,
      code: decision.code,
      itemIds: decision.item_ids,
      detail: decision.detail,
      occurredAt: decision.occurred_at,
    }))
    .sort((a, b) => Date.parse(a.occurredAt) - Date.parse(b.occurredAt));
}

/** Builds a candidate item_id -> reader href resolver from a version->document map. */
export function readerHref(
  candidate: Candidate,
  documentIdByVersionId: Readonly<Record<string, string>>,
): string | null {
  const documentId = documentIdByVersionId[candidate.document_version_id];
  if (!documentId) return null;
  const params = new URLSearchParams({ span: candidate.source_span_id });
  return `/reader/${encodeURIComponent(documentId)}?${params.toString()}`;
}
