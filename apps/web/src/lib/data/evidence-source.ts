import type { components } from "@fel/contracts";
import type { DocumentMeta, ReaderResponse } from "../contracts";

export type Page<T> = {
  items: T[];
  nextCursor: string | null;
  previousCursor: string | null;
  limit: number;
};
export type PageOptions = { limit?: number; cursor?: string; order?: "asc" | "desc" };
export type EvidenceScope = { asOf?: string; corpusVersionId?: string | null };
export type ReaderPageOptions = EvidenceScope & {
  includeSiblings?: boolean;
  siblingLimit?: number;
  siblingCursor?: string;
  siblingOrder?: "asc" | "desc";
  documentVersionId?: string;
};
export type DocumentVersionReference = components["schemas"]["DocumentVersionReference"];

/** Explicit bounded pages; a reader response always contains complete target evidence. */
export interface EvidenceSource {
  readonly entityIds: readonly string[];
  listDocuments(entityId: string, options?: PageOptions): Promise<Page<DocumentMeta>>;
  getDocument(documentId: string, scope?: EvidenceScope): Promise<DocumentMeta | null>;
  getReader(documentId: string, options?: ReaderPageOptions): Promise<ReaderResponse | null>;
  resolveDocumentVersions(
    versionIds: readonly string[],
    scope: EvidenceScope,
  ): Promise<DocumentVersionReference[]>;
}
