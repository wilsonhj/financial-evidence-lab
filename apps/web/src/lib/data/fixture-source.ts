import type {
  DocumentMeta,
  FinancialFactRecord,
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
import type { EvidenceSource, EvidenceSourceCapabilities } from "./evidence-source";

/**
 * Fixture-backed EvidenceSource serving the committed synthetic filing.
 * Every method returns fresh copies so callers can never mutate the fixture.
 *
 * `getSections`/`getSpans` take a DOCUMENT id (DocumentMeta.id) and resolve it
 * to the document's ACTIVE parsed version internally — document -> version
 * resolution is the source's job, never the UI's (integration-lead ruling,
 * PR #79). Returned records still carry `document_version_id` for
 * display/provenance only.
 */
export class FixtureEvidenceSource implements EvidenceSource {
  readonly capabilities: EvidenceSourceCapabilities = {
    sections: true,
    spans: true,
    facts: true,
  };

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
}

export const fixtureEvidenceSource = new FixtureEvidenceSource();
