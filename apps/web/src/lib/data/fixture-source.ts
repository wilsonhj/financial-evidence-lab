import type {
  DocumentMeta,
  FinancialFactRecord,
  SectionRecord,
  SourceSpanRecord,
} from "../contracts";
import {
  fixtureDocuments,
  fixtureFacts,
  fixtureSections,
  fixtureSpans,
} from "../fixtures/synthetic-filing";
import type { EvidenceSource } from "./evidence-source";

/**
 * Fixture-backed EvidenceSource serving the committed synthetic filing.
 * Every method returns fresh copies so callers can never mutate the fixture.
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
    return Promise.resolve(
      fixtureSections
        .filter((section) => section.document_version_id === documentId)
        .map((section) => ({ ...section })),
    );
  }

  getSpans(documentId: string): Promise<SourceSpanRecord[]> {
    return Promise.resolve(
      fixtureSpans
        .filter((record) => record.span.document_version_id === documentId)
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
