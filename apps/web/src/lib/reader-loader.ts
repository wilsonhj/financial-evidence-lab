import type {
  DocumentMeta,
  FinancialFactRecord,
  ReaderResponse,
  SectionRecord,
  SourceSpanRecord,
} from "./contracts";
import type { CitationIntegrityFailure } from "./citation-integrity";
import { verifySpanIntegrity } from "./citation-integrity";
import type { EvidenceSource } from "./data";

export interface ReaderData {
  document: DocumentMeta;
  documents: DocumentMeta[];
  /** Only the target's sections; siblings deliberately omit canonical content. */
  sections: SectionRecord[];
  /** Verified target spans plus sibling provenance spans used for attribution. */
  spans: SourceSpanRecord[];
  facts: FinancialFactRecord[];
  documentIdBySectionId: Record<string, string>;
  documentIdBySpanId: Record<string, string>;
  integrityFailures: CitationIntegrityFailure[];
  scope: Pick<ReaderResponse, "as_of" | "corpus_version_id" | "selection_policy">;
}

export type ReaderLoadResult = { kind: "not_found" } | { kind: "ready"; data: ReaderData };

function toSectionRecord(section: ReaderResponse["document"]["sections"][number]): SectionRecord {
  return {
    id: section.id,
    document_version_id: section.document_version_id,
    ...(section.parent_id ? { parent_id: section.parent_id } : {}),
    order: section.ord,
    level: Math.max(1, section.heading_path.length),
    title: section.heading,
    start_char: section.start_char,
    end_char: section.end_char,
    content: section.content,
  };
}

/**
 * Converts one snapshot-consistent ADR-0005 response into the existing reader
 * view model. Only target spans can be hash-verified because sibling blocks
 * intentionally omit canonical section content; sibling spans are never
 * highlighted or quoted while viewing the target.
 */
export async function loadReaderData(
  source: EvidenceSource,
  documentId: string,
): Promise<ReaderLoadResult> {
  const response = await source.getReader(documentId);
  if (!response) return { kind: "not_found" };

  const target = response.document;
  const sections = target.sections.map(toSectionRecord);
  const targetVerification = verifySpanIntegrity(sections, target.spans);
  const documents = [target.meta, ...response.siblings.map((sibling) => sibling.meta)];
  const siblingSpans = response.siblings.flatMap((sibling) => sibling.spans);
  const facts: FinancialFactRecord[] = [
    ...target.facts,
    ...response.siblings.flatMap((sibling) => sibling.facts),
  ];

  const documentIdBySectionId: Record<string, string> = {};
  for (const section of sections) documentIdBySectionId[section.id] = target.meta.id;

  const documentIdBySpanId: Record<string, string> = {};
  for (const span of target.spans) documentIdBySpanId[span.id] = target.meta.id;
  for (const sibling of response.siblings) {
    for (const span of sibling.spans) documentIdBySpanId[span.id] = sibling.meta.id;
  }

  return {
    kind: "ready",
    data: {
      document: target.meta,
      documents,
      sections,
      spans: [...targetVerification.verified, ...siblingSpans],
      facts,
      documentIdBySectionId,
      documentIdBySpanId,
      integrityFailures: targetVerification.failures,
      scope: {
        as_of: response.as_of,
        corpus_version_id: response.corpus_version_id,
        selection_policy: response.selection_policy,
      },
    },
  };
}
