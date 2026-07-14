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

  // Regression (finding 4a): with two amendments, Amendment No. 2 must
  // supersede Amendment No. 1 — amendments can supersede amendments — and the
  // original's authoritative amendment is the LATEST one.
  it("chains multiple amendments: the later amendment supersedes the earlier one", () => {
    const secondAmendment: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-000000000003",
      accession: "0000111111-26-000260",
      published_at: "2026-07-01T12:00:00Z",
    };
    const links = linkAmendments([...fixtureDocuments, secondAmendment]);
    expect(links).toEqual([
      { originalId: DOC_10Q_ID, amendmentId: DOC_10QA_ID },
      { originalId: DOC_10QA_ID, amendmentId: secondAmendment.id },
    ]);
  });

  // Regression (finding 4b): published_at used to be compared as a raw
  // string. "2026-06-12T23:59:00+03:00" sorts AFTER "2026-06-12T21:30:00Z"
  // lexicographically but is the EARLIER instant (20:59Z < 21:30Z).
  it("orders publication by instant, not by raw timestamp string", () => {
    const offsetAmendment: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-000000000011",
      accession: "0000111111-26-000201",
      published_at: "2026-06-12T23:59:00+03:00", // 2026-06-12T20:59:00Z
    };
    const utcAmendment: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-000000000012",
      accession: "0000111111-26-000202",
      published_at: "2026-06-12T21:30:00Z",
    };
    const links = linkAmendments([fixtureDocuments[0]!, offsetAmendment, utcAmendment]);
    // The offset amendment is the earlier instant: it amends the original;
    // the UTC amendment is later and supersedes the offset amendment.
    expect(links).toEqual([
      { originalId: DOC_10Q_ID, amendmentId: offsetAmendment.id },
      { originalId: offsetAmendment.id, amendmentId: utcAmendment.id },
    ]);
    // A raw string comparison would also misreport the authoritative chain end.
    expect(amendmentStatusFor(DOC_10Q_ID, links)).toEqual({
      kind: "superseded",
      byDocumentId: utcAmendment.id,
    });
  });

  // Regression (finding 4c): undefined === undefined used to count as a
  // period match, cross-linking period-less documents.
  it("never links documents with missing period fields", () => {
    const periodlessOriginal: DocumentMeta = {
      ...fixtureDocuments[0]!,
      id: "aaaaaaaa-0000-4000-8000-000000000021",
      period_start: undefined,
      period_end: undefined,
    };
    const periodlessAmendment: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-000000000022",
      period_start: undefined,
      period_end: undefined,
    };
    expect(linkAmendments([periodlessOriginal, periodlessAmendment])).toEqual([]);

    const partialPeriodAmendment: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-000000000023",
      period_end: undefined,
    };
    expect(linkAmendments([fixtureDocuments[0]!, partialPeriodAmendment])).toEqual([]);
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

  // Regression (finding 4a): the superseded banner must point at the LATEST
  // amendment, and an earlier amendment reads as superseded itself.
  it("follows the amendment chain to the authoritative (latest) amendment", () => {
    const secondAmendment: DocumentMeta = {
      ...fixtureDocuments[1]!,
      id: "aaaaaaaa-0000-4000-8000-000000000003",
      accession: "0000111111-26-000260",
      published_at: "2026-07-01T12:00:00Z",
    };
    const chained = linkAmendments([...fixtureDocuments, secondAmendment]);
    expect(amendmentStatusFor(DOC_10Q_ID, chained)).toEqual({
      kind: "superseded",
      byDocumentId: secondAmendment.id,
    });
    expect(amendmentStatusFor(DOC_10QA_ID, chained)).toEqual({
      kind: "superseded",
      byDocumentId: secondAmendment.id,
    });
    expect(amendmentStatusFor(secondAmendment.id, chained)).toEqual({
      kind: "amendment",
      amendsDocumentId: DOC_10QA_ID,
    });
  });
});
