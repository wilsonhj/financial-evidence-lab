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
import type {
  EvidenceSource,
  PageOptions,
  Page,
  ReaderPageOptions,
  EvidenceScope,
  DocumentVersionReference,
} from "./evidence-source";
import { MOCK_CORPUS_VERSION_ID } from "../observatory/fixtures/synthetic-trace";
import { fixturePage } from "./pagination";
import { EvidenceContractError } from "./http-source";

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
  readonly entityIds = [...new Set(fixtureDocuments.map((doc) => doc.entity_id))];

  listDocuments(entityId: string, options: PageOptions = {}): Promise<Page<DocumentMeta>> {
    const documents = fixtureDocuments
      .filter((doc) => doc.entity_id === entityId)
      .map((doc) => ({ ...doc }))
      .sort(
        (a, b) =>
          a.published_at.localeCompare(b.published_at) ||
          a.accession.localeCompare(b.accession) ||
          a.id.localeCompare(b.id),
      );
    return Promise.resolve(
      fixturePage(documents, options, `documents:${entityId}`, EvidenceContractError),
    );
  }

  resolveDocumentVersions(
    versionIds: readonly string[],
    scope: EvidenceScope,
  ): Promise<DocumentVersionReference[]> {
    if (scope.corpusVersionId && scope.corpusVersionId !== MOCK_CORPUS_VERSION_ID)
      return Promise.resolve([]);
    const ids = [...new Set(versionIds)];
    if (ids.length > 200) throw new EvidenceContractError("version resolution exceeds 200 ids");
    return Promise.resolve(
      fixtureDocuments
        .filter(
          (doc) =>
            ids.includes(fixtureActiveVersionIdByDocumentId[doc.id]!) &&
            (!scope.asOf || Date.parse(doc.published_at) <= Date.parse(scope.asOf)),
        )
        .map((doc) => ({
          document_version_id: fixtureActiveVersionIdByDocumentId[doc.id]!,
          document_id: doc.id,
        })),
    );
  }

  getDocument(documentId: string, scope: EvidenceScope = {}): Promise<DocumentMeta | null> {
    const doc = fixtureDocuments.find(
      (candidate) =>
        candidate.id === documentId &&
        (!scope.asOf || Date.parse(candidate.published_at) <= Date.parse(scope.asOf)),
    );
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
          ...record,
          fact: {
            ...record.fact,
            period: { ...record.fact.period },
            dimensions: record.fact.dimensions ? { ...record.fact.dimensions } : undefined,
          },
        })),
    );
  }

  async getReader(
    documentId: string,
    options: ReaderPageOptions = {},
  ): Promise<ReaderResponse | null> {
    if (options.corpusVersionId && options.corpusVersionId !== MOCK_CORPUS_VERSION_ID) return null;
    if (
      options.siblingLimit !== undefined &&
      (!Number.isInteger(options.siblingLimit) ||
        options.siblingLimit < 1 ||
        options.siblingLimit > 20)
    )
      throw new EvidenceContractError("invalid sibling limit");
    const target = fixtureDocuments.find((document) => document.id === documentId);
    if (!target) return null;

    const versionId = fixtureActiveVersionIdByDocumentId[documentId];
    if (!versionId || (options.documentVersionId && options.documentVersionId !== versionId))
      return null;
    if (options.asOf && Date.parse(target.published_at) > Date.parse(options.asOf)) return null;

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

    const allSiblings = fixtureDocuments
      .filter(
        (document) =>
          document.id !== documentId &&
          document.entity_id === target.entity_id &&
          (!options.asOf || Date.parse(document.published_at) <= Date.parse(options.asOf)),
      )
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

    const asOf = options.asOf ?? "2026-12-31T23:59:59Z";
    const pageMode =
      options.includeSiblings === false ||
      options.siblingLimit !== undefined ||
      options.siblingCursor !== undefined ||
      options.siblingOrder !== undefined;
    const page = fixturePage(
      allSiblings.sort(
        (a, b) =>
          a.meta.published_at.localeCompare(b.meta.published_at) ||
          a.meta.accession.localeCompare(b.meta.accession) ||
          a.meta.id.localeCompare(b.meta.id),
      ),
      {
        limit: options.siblingLimit ?? (options.siblingCursor ? undefined : 10),
        cursor: options.siblingCursor,
        order: options.siblingOrder,
      },
      `reader:${documentId}:${versionId}:${asOf}:${options.corpusVersionId ?? ""}`,
      EvidenceContractError,
    );
    const siblings = options.includeSiblings === false ? [] : pageMode ? page.items : allSiblings;
    return {
      as_of: asOf,
      corpus_version_id: options.corpusVersionId ?? null,
      selection_policy: options.corpusVersionId ? "corpus_pinned" : "latest_parsed",
      document: {
        meta: { ...target },
        document_version_id: versionId,
        sections: readerSections,
        spans: spansForVersion(versionId),
        facts: factsForVersion(versionId),
      },
      siblings,
      ...(pageMode
        ? {
            sibling_page: {
              scope: options.includeSiblings === false ? ("excluded" as const) : ("page" as const),
              returned: siblings.length,
              limit: page.limit,
              complete:
                options.includeSiblings !== false && !page.nextCursor && !page.previousCursor,
              next_cursor: options.includeSiblings === false ? null : page.nextCursor,
              previous_cursor: options.includeSiblings === false ? null : page.previousCursor,
            },
          }
        : {}),
    };
  }
}

export const fixtureEvidenceSource = new FixtureEvidenceSource();
