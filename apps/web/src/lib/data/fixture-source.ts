import type {
  DocumentMeta,
  FinancialFactRecord,
  ReaderFactRecord,
  ReaderResponse,
  ReaderSection,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";
import {
  fixtureActiveVersionIdByDocumentId,
  fixtureDocuments,
  fixtureFacts,
  fixtureSections,
  fixtureSpans,
} from "../fixtures/synthetic-filing";
import type { EvidenceSource } from "./evidence-source";

/**
 * Fixture-backed EvidenceSource serving the committed synthetic filing.
 * Every method returns fresh copies so callers can never mutate the fixture.
 *
 * `getSections`/`getSpans` take a DOCUMENT id (DocumentMeta.id) and resolve it
 * to the document's ACTIVE parsed version internally — document -> version
 * resolution is the source's job, never the UI's (integration-lead ruling,
 * PR #79). Returned records still carry `document_version_id` for
 * display/provenance only.
 *
 * Coordinate contract (issue #87): sections carry GLOBAL canonical ranges and
 * span offsets are GLOBAL canonical offsets, exactly as ingestion persists
 * them; the source serves them verbatim and never rewrites offsets.
 */
export class FixtureEvidenceSource implements EvidenceSource {
  listDocuments(): Promise<DocumentMeta[]> {
    return Promise.resolve(fixtureDocuments.map((doc) => ({ ...doc })));
  }

  getDocument(documentId: string): Promise<DocumentMeta | null> {
    const doc = fixtureDocuments.find((candidate) => candidate.id === documentId);
    return Promise.resolve(doc ? { ...doc } : null);
  }

  getSections(documentId: string): Promise<SectionRecord[]> {
    const versionId = fixtureActiveVersionIdByDocumentId[documentId];
    return Promise.resolve(
      fixtureSections
        .filter((section) => section.document_version_id === versionId)
        .map((section) => ({ ...section })),
    );
  }

  getSpans(documentId: string): Promise<SourceSpanRecord[]> {
    const versionId = fixtureActiveVersionIdByDocumentId[documentId];
    return Promise.resolve(
      fixtureSpans
        .filter((record) => record.span.document_version_id === versionId)
        .map((record) => ({ id: record.id, span: { ...record.span } })),
    );
  }

  getFacts(entityId: string): Promise<FinancialFactRecord[]> {
    return Promise.resolve(
      fixtureFacts
        .filter((record) => record.fact.entity_id === entityId)
        .map((record) => ({
          id: record.id,
          fact: {
            ...record.fact,
            period: { ...record.fact.period },
            dimensions: record.fact.dimensions ? { ...record.fact.dimensions } : undefined,
          },
        })),
    );
  }

  async getReader(documentId: string): Promise<ReaderResponse | null> {
    const target = fixtureDocuments.find((document) => document.id === documentId);
    if (!target) return null;

    const versionId = fixtureActiveVersionIdByDocumentId[documentId];
    if (!versionId) return null;

    const sections = fixtureSections.filter((section) => section.document_version_id === versionId);
    const byId = new Map(sections.map((section) => [section.id, section]));
    const headingPath = (section: SectionRecord): string[] => {
      const parent = section.parent_id ? byId.get(section.parent_id) : undefined;
      return parent ? [...headingPath(parent), section.title] : [section.title];
    };
    const readerSections: ReaderSection[] = sections.map((section) => ({
      id: section.id,
      document_version_id: section.document_version_id,
      ...(section.parent_id ? { parent_id: section.parent_id } : {}),
      heading: section.title,
      heading_path: headingPath(section),
      ord: section.order,
      start_char: section.start_char,
      end_char: section.end_char,
      content: section.content,
    }));

    const spansForVersion = (id: string) =>
      fixtureSpans
        .filter((record) => record.span.document_version_id === id)
        .map((record) => ({ id: record.id, span: { ...record.span } }));
    const factsForVersion = (id: string): ReaderFactRecord[] => {
      const spanIds = new Set(spansForVersion(id).map((record) => record.id));
      return fixtureFacts
        .filter((record) => spanIds.has(record.fact.source_span_id))
        .map((record) => ({
          id: record.id,
          document_version_id: id,
          fact: {
            ...record.fact,
            period: { ...record.fact.period },
            dimensions: record.fact.dimensions ? { ...record.fact.dimensions } : undefined,
          },
        }));
    };

    const siblings = fixtureDocuments
      .filter((document) => document.id !== documentId && document.entity_id === target.entity_id)
      .flatMap((document) => {
        const siblingVersionId = fixtureActiveVersionIdByDocumentId[document.id];
        if (!siblingVersionId) return [];
        return [
          {
            meta: { ...document },
            document_version_id: siblingVersionId,
            spans: spansForVersion(siblingVersionId),
            facts: factsForVersion(siblingVersionId),
          },
        ];
      });

    return {
      as_of: "2026-12-31T23:59:59Z",
      corpus_version_id: null,
      selection_policy: "latest_parsed",
      document: {
        meta: { ...target },
        document_version_id: versionId,
        sections: readerSections,
        spans: spansForVersion(versionId),
        facts: factsForVersion(versionId),
      },
      siblings,
    };
  }
}

export const fixtureEvidenceSource = new FixtureEvidenceSource();
