import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";

/**
 * Which evidence collections a source can actually serve. The reader page
 * checks these before calling the corresponding methods and renders a
 * graceful "details not yet available" state instead of crashing when a
 * source (e.g. the HTTP source against the current ingestion API contract)
 * cannot provide sections, spans, or facts yet.
 */
export interface EvidenceSourceCapabilities {
  sections: boolean;
  spans: boolean;
  facts: boolean;
}

/**
 * Typed data-access boundary for the evidence reader. The UI only ever talks
 * to this interface; today it is backed by the committed synthetic fixture
 * (FixtureEvidenceSource) and the HTTP implementation (HttpEvidenceSource)
 * covers the document endpoints of the frozen ingestion API contract.
 *
 * ID semantics (integration-lead ruling, PR #79): `documentId` parameters are
 * ALWAYS `documents.id` (DocumentMeta.id). Sections/spans/facts internally
 * hang off `document_versions.id` — a DIFFERENT UUID. `getSections`/`getSpans`
 * are document-scoped: they return data for the ACTIVE parsed version of the
 * given document, and the document -> version resolution is the source's job,
 * never the UI's. `document_version_id` on returned records is
 * display/provenance metadata only; the UI must never compare it against
 * DocumentMeta.id.
 */
export interface EvidenceSource {
  /** What this source can serve; the UI gates its calls on these flags. */
  readonly capabilities: EvidenceSourceCapabilities;
  /** All ingested documents visible to the workspace. */
  listDocuments(): Promise<DocumentMeta[]>;
  /** One document by id (DocumentMeta.id), or null when unknown. */
  getDocument(documentId: string): Promise<DocumentMeta | null>;
  /**
   * Extracted sections of the document's active version, in document order.
   * Sections carry GLOBAL canonical-text ranges (`start_char`/`end_char`)
   * with `content` being exactly that canonical slice.
   */
  getSections(documentId: string): Promise<SectionRecord[]>;
  /**
   * Source spans anchored in the document's active version. Span offsets are
   * GLOBAL canonical-document offsets (never section-local); the UI derives
   * local render anchors as `span.start_char - section.start_char` and never
   * rewrites the persisted values.
   */
  getSpans(documentId: string): Promise<SourceSpanRecord[]>;
  /**
   * Normalized facts for an entity across all of its documents —
   * cross-version access is required for duplicate comparison and
   * amendment/restatement flagging.
   */
  getFacts(entityId: string): Promise<FinancialFactRecord[]>;
}
