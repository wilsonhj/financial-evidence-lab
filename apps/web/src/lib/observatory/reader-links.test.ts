import { describe, expect, it } from "vitest";

import { fixtureEvidenceSource } from "../data";
import {
  DOC_10QA_ID,
  DOC_10QA_VERSION_ID,
  DOC_10Q_ID,
  DOC_10Q_VERSION_ID,
} from "../fixtures/synthetic-filing";
import { buildDocumentIdByVersionId } from "./reader-links";

describe("buildDocumentIdByVersionId", () => {
  it("maps each document version to its DocumentMeta id via the reader source", async () => {
    const map = await buildDocumentIdByVersionId(
      fixtureEvidenceSource,
      [DOC_10Q_VERSION_ID, DOC_10QA_VERSION_ID],
      {},
    );
    expect(map[DOC_10Q_VERSION_ID]).toBe(DOC_10Q_ID);
    expect(map[DOC_10QA_VERSION_ID]).toBe(DOC_10QA_ID);
  });
});

it("resolves only distinct actual trace IDs in bounded scoped batches", async () => {
  const ids = Array.from({ length: 401 }, (_, index) => `version-${index}`);
  const calls: string[][] = [];
  const scope = { asOf: "2026-06-30T23:59:59Z", corpusVersionId: "trace-pin" };
  const source = Object.create(fixtureEvidenceSource) as typeof fixtureEvidenceSource;
  source.resolveDocumentVersions = async (batch, actualScope) => {
    expect(actualScope).toEqual(scope);
    calls.push([...batch]);
    return batch.map((id) => ({ document_version_id: id, document_id: `document-${id}` }));
  };
  source.listDocuments = () => {
    throw new Error("must not scan corpus");
  };
  source.getReader = () => {
    throw new Error("must not read filing evidence");
  };
  const map = await buildDocumentIdByVersionId(source, [...ids, ids[0]!], scope);
  expect(calls.map((batch) => batch.length)).toEqual([200, 200, 1]);
  expect(Object.keys(map)).toHaveLength(401);
});
