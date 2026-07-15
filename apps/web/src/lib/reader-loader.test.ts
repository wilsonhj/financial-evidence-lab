import { describe, expect, it } from "vitest";

import type { ReaderResponse } from "./contracts";
import type { EvidenceSource } from "./data";
import { fixtureEvidenceSource } from "./data";
import { sha256Hex } from "./citation-integrity";
import { loadReaderData } from "./reader-loader";
import {
  DOC_10Q_ID,
  DOC_10QA_ID,
  fixtureDocuments,
  fixtureFacts,
  fixtureSpans,
} from "./fixtures/synthetic-filing";

function sourceWithMutation(mutate: (response: ReaderResponse) => void): EvidenceSource {
  return {
    listDocuments: () => fixtureEvidenceSource.listDocuments(),
    getReader: async (documentId) => {
      const response = await fixtureEvidenceSource.getReader(documentId);
      if (response) mutate(response);
      return response;
    },
  };
}

describe("loadReaderData", () => {
  it("returns not_found for an unknown document id", async () => {
    const result = await loadReaderData(
      fixtureEvidenceSource,
      "aaaaaaaa-0000-4000-8000-0000000cafe0",
    );
    expect(result).toEqual({ kind: "not_found" });
  });

  it("assembles the target and siblings from one composite snapshot", async () => {
    const result = await loadReaderData(fixtureEvidenceSource, DOC_10Q_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    const { data } = result;

    expect(data.sections).toHaveLength(6);
    expect(
      data.sections.every((section) => data.documentIdBySectionId[section.id] === DOC_10Q_ID),
    ).toBe(true);
    expect(
      data.spans.filter((span) => data.documentIdBySpanId[span.id] === DOC_10Q_ID),
    ).toHaveLength(5);
    expect(
      data.facts.filter(
        (record) => data.documentIdBySpanId[record.fact.source_span_id] === DOC_10Q_ID,
      ),
    ).toHaveLength(6);
    expect(data.integrityFailures).toEqual([]);
    expect(data.spans).toHaveLength(fixtureSpans.length);
    expect(data.facts).toHaveLength(fixtureFacts.length);
    expect(data.documents.map((doc) => doc.id).sort()).toEqual([DOC_10Q_ID, DOC_10QA_ID].sort());
    expect(data.scope).toEqual({
      as_of: "2026-12-31T23:59:59Z",
      corpus_version_id: null,
      selection_policy: "latest_parsed",
    });
  });

  it("excludes and flags target spans failing offset or hash verification", async () => {
    const source = sourceWithMutation((response) => {
      response.document.spans[0]!.span.text_hash = `sha256:${sha256Hex("tampered text")}`;
      response.document.spans[1]!.span.end_char = 100_000;
    });

    const result = await loadReaderData(source, DOC_10Q_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;

    expect(result.data.integrityFailures.map((failure) => failure.reason).sort()).toEqual([
      "offsets_out_of_range",
      "text_hash_mismatch",
    ]);
    const failedIds = new Set(result.data.integrityFailures.map((failure) => failure.spanId));
    expect(result.data.spans.filter((span) => failedIds.has(span.id))).toEqual([]);
    expect(result.data.spans).toHaveLength(fixtureSpans.length - 2);
  });

  it("flags section-local target offsets instead of rendering a clamped citation", async () => {
    const source = sourceWithMutation((response) => {
      const span = response.document.spans[0]!;
      const section = response.document.sections.find(
        (candidate) => candidate.id === span.span.section_id,
      )!;
      span.span.start_char -= section.start_char;
      span.span.end_char -= section.start_char;
    });

    const result = await loadReaderData(source, DOC_10Q_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    expect(result.data.integrityFailures.map((failure) => failure.reason)).toEqual([
      "offsets_out_of_range",
    ]);
  });

  it("does not try to hash-verify sibling spans without sibling content", async () => {
    const source = sourceWithMutation((response) => {
      response.siblings[0]!.spans[0]!.span.text_hash = "sha256:bad";
    });
    const result = await loadReaderData(source, DOC_10Q_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    expect(result.data.integrityFailures).toEqual([]);
    expect(
      result.data.spans.some((span) => span.id === result.data.facts.at(-1)?.fact.source_span_id),
    ).toBe(true);
  });

  it("propagates source failures instead of mapping them to not_found", async () => {
    const source: EvidenceSource = {
      listDocuments: () => Promise.resolve([]),
      getReader: () => Promise.reject(new Error("api unavailable")),
    };
    await expect(loadReaderData(source, DOC_10Q_ID)).rejects.toThrow("api unavailable");
  });

  it("only includes same-entity documents returned by the composite source", async () => {
    const result = await loadReaderData(fixtureEvidenceSource, DOC_10QA_ID);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    for (const doc of result.data.documents) {
      expect(doc.entity_id).toBe(fixtureDocuments[0]!.entity_id);
    }
  });
});
