import type { components } from "@fel/contracts";

import type { RetrievalStreamOpener } from "./sse";

export type CreateQuery = components["schemas"]["CreateQuery"];
export type QueryAccepted = components["schemas"]["QueryAccepted"];
export type QuerySnapshot = components["schemas"]["QuerySnapshot"];
export type RetrievalTrace = components["schemas"]["RetrievalTrace"];
export type EvidenceFeedback = components["schemas"]["EvidenceFeedback"];
export type QueryPlan = components["schemas"]["QueryPlan"];
export type Candidate = components["schemas"]["Candidate"];
export type CandidateContribution = components["schemas"]["CandidateContribution"];
export type RetrievalDecision = components["schemas"]["RetrievalDecision"];
export type RetrievalClaim = components["schemas"]["RetrievalClaim"];
export type RetrievalCitation = components["schemas"]["RetrievalCitation"];

/**
 * Server-only Observatory boundary. Every method consumes the frozen ADR-0006
 * query/trace contract. Bearer auth lives entirely behind this interface; the
 * UI never sees a token and never assembles request shapes by hand.
 */
export interface ObservatoryQuerySource {
  /** Create an immutable query + first run. Idempotency-Key dedupes retries. */
  createQuery(input: CreateQuery, idempotencyKey: string): Promise<QueryAccepted>;
  /** Immutable query snapshot with its run history. */
  getQuery(queryId: string): Promise<QuerySnapshot>;
  /** Unchanged child run pinned to the original plan (parent-linked rerun). */
  createRerun(queryId: string, idempotencyKey: string): Promise<QueryAccepted>;
  /** Immutable trace snapshot for one run (used for stored replay and compare). */
  getRun(runId: string): Promise<RetrievalTrace>;
  /** Append-only evidence feedback for one item within a run. */
  submitFeedback(runId: string, feedback: EvidenceFeedback, idempotencyKey: string): Promise<void>;
  /** Opener for the resumable live event stream of one run. */
  openEventStream(runId: string): RetrievalStreamOpener;
}
