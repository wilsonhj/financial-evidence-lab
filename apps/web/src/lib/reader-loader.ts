import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "./contracts";
import type { CitationIntegrityFailure } from "./citation-integrity";
import { verifySpanIntegrity } from "./citation-integrity";
import type { EvidenceSource } from "./data";

/** Everything the EvidenceReader needs, fully resolved server-side. */
export interface ReaderData {
  document: DocumentMeta;
  /** All documents of the viewed document's entity (amendment linkage). */
  documents: DocumentMeta[];
  /** Sections across the entity's documents (document-scoped fetches, merged). */
  sections: SectionRecord[];
  /** Integrity-verified spans across the entity's documents. */
  spans: SourceSpanRecord[];
  /** All normalized facts of the entity. */
  facts: FinancialFactRecord[];
  /**
   * Provenance maps built from the per-document fetches. These — not
   * `document_version_id` — are how the UI attributes a section/span to a
   * document (integration-lead ruling: never compare version ids against
   * DocumentMeta.id).
   */
  documentIdBySectionId: Record<string, string>;
  documentIdBySpanId: Record<string, string>;
  /** Spans excluded fail-closed because offsets or text_hash did not verify. */
  integrityFailures: CitationIntegrityFailure[];
}

export type ReaderLoadResult =
  | { kind: "not_found" }
  /** The source cannot serve sections/spans/facts yet (see capabilities). */
  | { kind: "details_unavailable"; document: DocumentMeta }
  | { kind: "ready"; data: ReaderData };

/**
 * Loads and assembles all reader data for one document. Independent fetches
 * run in parallel; only `getFacts` waits on `getDocument` (it needs the
 * entity id). Spans are verified fail-closed before they ever reach the UI.
 */
export async function loadReaderData(
  source: EvidenceSource,
  documentId: string,
): Promise<ReaderLoadResult> {
  const [document, allDocuments] = await Promise.all([
    source.getDocument(documentId),
    source.listDocuments(),
  ]);
  if (!document) return { kind: "not_found" };

  const { capabilities } = source;
  if (!capabilities.sections || !capabilities.spans || !capabilities.facts) {
    return { kind: "details_unavailable", document };
  }

  const documents = allDocuments.filter((doc) => doc.entity_id === document.entity_id);

  // Sections and spans across every document of this entity: duplicate
  // comparison and restatement flagging must see sibling filings.
  const [facts, perDocument] = await Promise.all([
    source.getFacts(document.entity_id),
    Promise.all(
      documents.map(async (doc) => {
        const [sections, spans] = await Promise.all([
          source.getSections(doc.id),
          source.getSpans(doc.id),
        ]);
        return { doc, sections, spans };
      }),
    ),
  ]);

  const sections: SectionRecord[] = [];
  const rawSpans: SourceSpanRecord[] = [];
  const documentIdBySectionId: Record<string, string> = {};
  const documentIdBySpanId: Record<string, string> = {};
  for (const entry of perDocument) {
    for (const section of entry.sections) {
      sections.push(section);
      documentIdBySectionId[section.id] = entry.doc.id;
    }
    for (const span of entry.spans) {
      rawSpans.push(span);
      documentIdBySpanId[span.id] = entry.doc.id;
    }
  }

  const { verified: spans, failures: integrityFailures } = verifySpanIntegrity(sections, rawSpans);

  return {
    kind: "ready",
    data: {
      document,
      documents,
      sections,
      spans,
      facts,
      documentIdBySectionId,
      documentIdBySpanId,
      integrityFailures,
    },
  };
}
