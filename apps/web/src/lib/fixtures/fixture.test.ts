import { createHash } from "node:crypto";
import { createRequire } from "node:module";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { extractSpanText } from "../spans";
import { fixtureEvidenceSource } from "../data/fixture-source";
import {
  DOC_10Q_ID,
  DOC_10Q_VERSION_ID,
  DOC_10QA_ID,
  DOC_10QA_VERSION_ID,
  ENTITY_ID,
  fixtureActiveVersionIdByDocumentId,
  fixtureDocuments,
  fixtureFacts,
  fixtureSections,
  fixtureSpans,
} from "./synthetic-filing";

const require = createRequire(import.meta.url);
const sourceSpanSchema = require("@fel/contracts/schemas/source-span.schema.json") as object;
const financialFactSchema = require("@fel/contracts/schemas/financial-fact.schema.json") as object;

// TODO(contract-change): this ajv setup is duplicated with
// packages/contracts/contracts.test.ts; deduplicating it means exporting a
// validator from the frozen contracts package, so it is deliberately left
// as-is until a contract-change issue/ADR lands.
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
const validateSpan = ajv.compile(sourceSpanSchema);
const validateFact = ajv.compile(financialFactSchema);

describe("synthetic filing fixture", () => {
  it("spans conform to the frozen source-span contract", () => {
    for (const record of fixtureSpans) {
      const valid = validateSpan(record.span);
      expect(valid, JSON.stringify(validateSpan.errors)).toBe(true);
    }
  });

  it("facts conform to the frozen financial-fact contract", () => {
    for (const record of fixtureFacts) {
      const valid = validateFact(record.fact);
      expect(valid, JSON.stringify(validateFact.errors)).toBe(true);
    }
  });

  it("every span's text_hash matches the sha256 of the exact cited text", () => {
    const sectionsById = new Map(fixtureSections.map((section) => [section.id, section]));
    for (const record of fixtureSpans) {
      const section = sectionsById.get(record.span.section_id);
      expect(section, `span ${record.id} references a known section`).toBeDefined();
      const text = extractSpanText(section!, record);
      expect(text, `span ${record.id} has valid offsets`).not.toBeNull();
      expect(text!.length, `span ${record.id} is non-empty`).toBe(
        record.span.end_char - record.span.start_char,
      );
      const digest = createHash("sha256").update(text!, "utf8").digest("hex");
      expect(`sha256:${digest}`).toBe(record.span.text_hash);
    }
  });

  it("spans and sections reference their own document version", () => {
    const sectionsById = new Map(fixtureSections.map((section) => [section.id, section]));
    for (const record of fixtureSpans) {
      expect(sectionsById.get(record.span.section_id)?.document_version_id).toBe(
        record.span.document_version_id,
      );
    }
  });

  // Regression (finding 1, ID conflation): documents.id and
  // document_versions.id are DIFFERENT UUID namespaces. The fixture used to
  // reuse the same UUID for both, masking UI code that compared
  // span.document_version_id against DocumentMeta.id.
  it("keeps document ids and document version ids distinct", () => {
    expect(DOC_10Q_VERSION_ID).not.toBe(DOC_10Q_ID);
    expect(DOC_10QA_VERSION_ID).not.toBe(DOC_10QA_ID);
    const documentIds = new Set(fixtureDocuments.map((doc) => doc.id));
    for (const section of fixtureSections) {
      expect(documentIds.has(section.document_version_id)).toBe(false);
    }
    for (const record of fixtureSpans) {
      expect(documentIds.has(record.span.document_version_id)).toBe(false);
    }
    for (const doc of fixtureDocuments) {
      expect(fixtureActiveVersionIdByDocumentId[doc.id]).toBeDefined();
      expect(fixtureActiveVersionIdByDocumentId[doc.id]).not.toBe(doc.id);
    }
  });

  it("every fact cites an existing span of the fixture entity", () => {
    const spanIds = new Set(fixtureSpans.map((record) => record.id));
    for (const record of fixtureFacts) {
      expect(spanIds.has(record.fact.source_span_id), `fact ${record.id}`).toBe(true);
      expect(record.fact.entity_id).toBe(ENTITY_ID);
    }
  });
});

describe("FixtureEvidenceSource", () => {
  it("serves documents, sections, spans, and facts from the fixture", async () => {
    expect(await fixtureEvidenceSource.listDocuments()).toEqual(fixtureDocuments);
    expect((await fixtureEvidenceSource.getDocument(DOC_10QA_ID))?.form).toBe("10-Q/A");
    expect(await fixtureEvidenceSource.getDocument("aaaaaaaa-0000-4000-8000-00000000cafe")).toBe(
      null,
    );
    expect((await fixtureEvidenceSource.getSections(DOC_10Q_ID)).map((s) => s.id)).toEqual(
      fixtureSections.filter((s) => s.document_version_id === DOC_10Q_VERSION_ID).map((s) => s.id),
    );
    expect(await fixtureEvidenceSource.getSpans(DOC_10QA_ID)).toHaveLength(2);
    expect(await fixtureEvidenceSource.getFacts(ENTITY_ID)).toHaveLength(fixtureFacts.length);
    expect(await fixtureEvidenceSource.getFacts("22222222-2222-4222-8222-222222222222")).toEqual(
      [],
    );
  });

  // Regression (finding 1): getSections/getSpans take a DOCUMENT id and must
  // resolve it to the active parsed version internally. The old source
  // filtered `document_version_id === documentId`, which returns nothing now
  // that the fixture keeps the two id namespaces distinct.
  it("resolves a document id to its active version when serving sections and spans", async () => {
    const sections = await fixtureEvidenceSource.getSections(DOC_10Q_ID);
    expect(sections.length).toBeGreaterThan(0);
    for (const section of sections) {
      expect(section.document_version_id).toBe(DOC_10Q_VERSION_ID);
    }
    const spans = await fixtureEvidenceSource.getSpans(DOC_10Q_ID);
    expect(spans.length).toBeGreaterThan(0);
    for (const record of spans) {
      expect(record.span.document_version_id).toBe(DOC_10Q_VERSION_ID);
    }
    // Asking with a version id (the conflated call) yields nothing: version
    // resolution is the source's job and version ids are not document ids.
    expect(await fixtureEvidenceSource.getSections(DOC_10Q_VERSION_ID)).toEqual([]);
    expect(await fixtureEvidenceSource.getSpans(DOC_10Q_VERSION_ID)).toEqual([]);
  });

  it("advertises full capabilities", () => {
    expect(fixtureEvidenceSource.capabilities).toEqual({
      sections: true,
      spans: true,
      facts: true,
    });
  });

  it("returns defensive copies, never fixture references", async () => {
    const documents = await fixtureEvidenceSource.listDocuments();
    documents[0]!.accession = "mutated";
    const facts = await fixtureEvidenceSource.getFacts(ENTITY_ID);
    facts[0]!.fact.value = "999";
    expect(fixtureDocuments[0]!.accession).toBe("0000111111-26-000123");
    expect(fixtureFacts[0]!.fact.value).toBe("1250");
  });
});
