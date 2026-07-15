import type { DocumentMeta, ReaderResponse } from "../contracts";

/**
 * Narrow reader boundary. All evidence for one filing comes from the frozen
 * ADR-0005 composite snapshot; the UI never assembles independently-versioned
 * section/span/fact calls.
 */
export interface EvidenceSource {
  /** Documents visible under the configured temporal scope. */
  listDocuments(): Promise<DocumentMeta[]>;
  /** Version-pinned evidence snapshot, or null only for an API 404. */
  getReader(documentId: string): Promise<ReaderResponse | null>;
}
