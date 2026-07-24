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
    const map = await buildDocumentIdByVersionId(fixtureEvidenceSource);
    expect(map[DOC_10Q_VERSION_ID]).toBe(DOC_10Q_ID);
    expect(map[DOC_10QA_VERSION_ID]).toBe(DOC_10QA_ID);
  });
});
