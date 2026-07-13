import { describe, expect, it } from "vitest";

import { amendmentStatusFor, linkAmendments } from "./amendments";
import { DOC_10Q_ID, DOC_10QA_ID, fixtureDocuments } from "./fixtures/synthetic-filing";
import type { DocumentMeta } from "./contracts";

describe("linkAmendments", () => {
  it("links the fixture 10-Q/A to the 10-Q it amends", () => {
    const links = linkAmendments(fixtureDocuments);
    expect(links).toEqual([{ originalId: DOC_10Q_ID, amendmentId: DOC_10QA_ID }]);
  });

  it("does not link filings of other entities or periods", () => {
    const otherEntity: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-00000000dead",
      entity_id: "22222222-2222-4222-8222-222222222222",
    };
    const otherPeriod: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-00000000beef",
      period_start: "2025-10-01",
      period_end: "2025-12-31",
    };
    const links = linkAmendments([fixtureDocuments[0]!, otherEntity, otherPeriod]);
    expect(links).toEqual([]);
  });

  it("picks the latest original when several precede the amendment", () => {
    const earlier: DocumentMeta = {
      ...fixtureDocuments[0]!,
      id: "aaaaaaaa-0000-4000-8000-00000000aaaa",
      published_at: "2026-04-20T10:00:00Z",
    };
    const links = linkAmendments([earlier, ...fixtureDocuments]);
    expect(links).toEqual([{ originalId: DOC_10Q_ID, amendmentId: DOC_10QA_ID }]);
  });
});

describe("amendmentStatusFor", () => {
  const links = linkAmendments(fixtureDocuments);

  it("marks the original as superseded by the amendment", () => {
    expect(amendmentStatusFor(DOC_10Q_ID, links)).toEqual({
      kind: "superseded",
      byDocumentId: DOC_10QA_ID,
    });
  });

  it("marks the amendment as amending the original", () => {
    expect(amendmentStatusFor(DOC_10QA_ID, links)).toEqual({
      kind: "amendment",
      amendsDocumentId: DOC_10Q_ID,
    });
  });

  it("reports unlinked documents as originals", () => {
    expect(amendmentStatusFor("aaaaaaaa-0000-4000-8000-00000000cafe", links)).toEqual({
      kind: "original",
    });
  });
});
