import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";

/**
 * Typed data-access boundary for the evidence reader. The UI only ever talks
 * to this interface; today it is backed by the committed synthetic fixture
 * (FixtureEvidenceSource) and the HTTP implementation (HttpEvidenceSource)
 * is stubbed against the ingestion API that lands with M1-INGESTION.
 */
export interface EvidenceSource {
  /** All ingested document versions visible to the workspace. */
  listDocuments(): Promise<DocumentMeta[]>;
  /** One document version by id, or null when unknown. */
  getDocument(documentId: string): Promise<DocumentMeta | null>;
  /** Extracted sections of a document version, in document order. */
  getSections(documentId: string): Promise<SectionRecord[]>;
  /** Source spans anchored in a document version. */
  getSpans(documentId: string): Promise<SourceSpanRecord[]>;
  /**
   * Normalized facts for an entity across all of its document versions —
   * cross-version access is required for duplicate comparison and
   * amendment/restatement flagging.
   */
  getFacts(entityId: string): Promise<FinancialFactRecord[]>;
}
