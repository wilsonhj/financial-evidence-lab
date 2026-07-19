export type { components, paths, operations } from "./generated/api";

/** Frozen schema registry: name -> versioned $id (see VERSIONING.md). */
export const SCHEMA_IDS = {
  sourceSpan: "https://contracts.fel.dev/schemas/source-span/v1",
  financialFact: "https://contracts.fel.dev/schemas/financial-fact/v1",
  claim: "https://contracts.fel.dev/schemas/claim/v1",
  citation: "https://contracts.fel.dev/schemas/citation/v1",
  jobEnvelope: "https://contracts.fel.dev/schemas/job-envelope/v1",
  tenantContext: "https://contracts.fel.dev/schemas/tenant-context/v1",
  error: "https://contracts.fel.dev/schemas/error/v1",
  readerResponse: "https://contracts.fel.dev/schemas/reader-response/v1",
  queryPlan: "https://contracts.fel.dev/schemas/query-plan/v1",
  retrievalEvent: "https://contracts.fel.dev/schemas/retrieval-event/v1",
  retrievalTrace: "https://contracts.fel.dev/schemas/retrieval-trace/v1",
  evidenceFeedback: "https://contracts.fel.dev/schemas/evidence-feedback/v1",
  extractionEvent: "https://contracts.fel.dev/schemas/extraction-event/v1",
  extractionPayload: "https://contracts.fel.dev/schemas/extraction-payload/v1",
} as const;

export const CONTRACT_VERSION = "0.4.0" as const;
