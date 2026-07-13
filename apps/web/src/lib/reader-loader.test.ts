import { describe, expect, it } from "vitest";

import type { EvidenceSource } from "./data";
import { fixtureEvidenceSource } from "./data";
import { sha256Hex } from "./citation-integrity";
import { loadReaderData } from "./reader-loader";
import {
  DOC_10Q_ID,
  DOC_10QA_ID,
  fixtureDocuments,
  fixtureFacts,
  fixtureSections,
  fixtureSpans,
} from "./fixtures/synthetic-filing";

describe("loadReaderData", () => {
  it("returns not_found for an unknown document id", async () => {
    const result = await loadReaderData(
      fixtureEvidenceSource,
      "aaaaaaaa-0000-4000-8000-0000000cafe0",
    );
    expect(result).toEqual({ kind: "not_found" });
  });

  // Regression (finding 1, ID conflation): with DISTINCT document and version
  // ids the old pipeline (UI filtering `document_version_id === documentId`)
  // produced an empty reader: no sections, no spans, no facts. The loader must
  // deliver all of them, attributed to documents via the provenance maps.
  it("assembles sections, spans, and facts for a document whose version id differs from its id", async () => {
    const result = await loadReaderData(fixtureEvidenceSource, DOC_10Q_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    const { data } = result;

    const ownSections = data.sections.filter(
      (section) => data.documentIdBySectionId[section.id] === DOC_10Q_ID,
    );
    expect(ownSections.length).toBe(6);

    const ownSpans = data.spans.filter((span) => data.documentIdBySpanId[span.id] === DOC_10Q_ID);
    expect(ownSpans.length).toBe(5);

    const ownFacts = data.facts.filter(
      (record) => data.documentIdBySpanId[record.fact.source_span_id] === DOC_10Q_ID,
    );
    expect(ownFacts.length).toBe(6);

    // Every fixture span verifies, so nothing is excluded.
    expect(data.integrityFailures).toEqual([]);
    expect(data.spans.length).toBe(fixtureSpans.length);
    expect(data.sections.length).toBe(fixtureSections.length);
    expect(data.facts.length).toBe(fixtureFacts.length);

    // Sibling filings of the entity are included for amendment comparison.
    expect(data.documents.map((doc) => doc.id).sort()).toEqual([DOC_10Q_ID, DOC_10QA_ID].sort());
  });

  // Regression (finding 2): a span that no longer verifies must be excluded
  // from the verified span set and surfaced as an integrity failure.
  it("excludes and flags spans failing offset or hash verification", async () => {
    const tamperedSource: EvidenceSource = {
      capabilities: { sections: true, spans: true, facts: true },
      listDocuments: () => fixtureEvidenceSource.listDocuments(),
      getDocument: (id) => fixtureEvidenceSource.getDocument(id),
      getSections: (id) => fixtureEvidenceSource.getSections(id),
      getFacts: (id) => fixtureEvidenceSource.getFacts(id),
      getSpans: async (id) => {
        const spans = await fixtureEvidenceSource.getSpans(id);
        if (id === DOC_10Q_ID && spans[0]) {
          spans[0].span.text_hash = `sha256:${sha256Hex("tampered text")}`;
          spans[1]!.span.end_char = 100_000; // out of range
        }
        return spans;
      },
    };

    const result = await loadReaderData(tamperedSource, DOC_10Q_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    const { data } = result;

    expect(data.integrityFailures.map((failure) => failure.reason).sort()).toEqual([
      "offsets_out_of_range",
      "text_hash_mismatch",
    ]);
    const failedIds = new Set(data.integrityFailures.map((failure) => failure.spanId));
    expect(failedIds.size).toBe(2);
    for (const span of data.spans) {
      expect(failedIds.has(span.id)).toBe(false);
    }
    expect(data.spans.length).toBe(fixtureSpans.length - 2);
  });

  // Regression (finding 3e): the reader used to await getSections/getSpans/
  // getFacts unguarded, crashing on sources that cannot serve them yet.
  it("returns details_unavailable instead of calling unsupported methods", async () => {
    const calls: string[] = [];
    const limitedSource: EvidenceSource = {
      capabilities: { sections: false, spans: false, facts: false },
      listDocuments: () => fixtureEvidenceSource.listDocuments(),
      getDocument: (id) => fixtureEvidenceSource.getDocument(id),
      getSections: () => {
        calls.push("getSections");
        return Promise.reject(new Error("not in contract"));
      },
      getSpans: () => {
        calls.push("getSpans");
        return Promise.reject(new Error("not in contract"));
      },
      getFacts: () => {
        calls.push("getFacts");
        return Promise.reject(new Error("not in contract"));
      },
    };

    const result = await loadReaderData(limitedSource, DOC_10Q_ID);
    expect(result.kind).toBe("details_unavailable");
    if (result.kind !== "details_unavailable") return;
    expect(result.document.id).toBe(DOC_10Q_ID);
    expect(calls).toEqual([]);
  });

  // Regression (finding 3c): source errors must propagate (to the route error
  // boundary), never be swallowed into a not-found.
  it("propagates evidence-source failures instead of mapping them to not_found", async () => {
    const failingSource: EvidenceSource = {
      ...fixtureEvidenceSource,
      capabilities: { sections: true, spans: true, facts: true },
      listDocuments: () => fixtureEvidenceSource.listDocuments(),
      getSections: (id) => fixtureEvidenceSource.getSections(id),
      getSpans: (id) => fixtureEvidenceSource.getSpans(id),
      getFacts: (id) => fixtureEvidenceSource.getFacts(id),
      getDocument: () => Promise.reject(new Error("api unavailable")),
    };
    await expect(loadReaderData(failingSource, DOC_10Q_ID)).rejects.toThrow("api unavailable");
  });

  it("only includes documents of the viewed document's entity", async () => {
    const result = await loadReaderData(fixtureEvidenceSource, DOC_10QA_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    for (const doc of result.data.documents) {
      expect(doc.entity_id).toBe(fixtureDocuments[0]!.entity_id);
    }
  });
});
