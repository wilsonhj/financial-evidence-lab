import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";

import type { DocumentMeta } from "../lib/contracts";
import { fixtureEvidenceSource } from "../lib/data";
import { loadReaderData, type ReaderData } from "../lib/reader-loader";
import { DOC_10Q_ID, DOC_10QA_ID } from "../lib/fixtures/synthetic-filing";
import { EvidenceReader } from "./EvidenceReader";

// next/link needs a Next.js runtime context; render it as a plain anchor.
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

async function readyData(documentId: string): Promise<ReaderData> {
  const result = await loadReaderData(fixtureEvidenceSource, documentId);
  if (result.kind !== "ready") throw new Error(`expected ready, got ${result.kind}`);
  return result.data;
}

function renderReader(documentId: string, data: ReaderData): string {
  return renderToStaticMarkup(
    <EvidenceReader
      documentId={documentId}
      documents={data.documents}
      sections={data.sections}
      spans={data.spans}
      facts={data.facts}
      documentIdBySectionId={data.documentIdBySectionId}
      documentIdBySpanId={data.documentIdBySpanId}
      integrityFailures={data.integrityFailures}
    />,
  );
}

describe("EvidenceReader rendering", () => {
  // Regression (finding 1, ID conflation): with distinct document/version ids
  // the old reader filtered sections and facts by
  // `document_version_id === DocumentMeta.id` and rendered an empty shell —
  // no sections, no span highlights, no facts.
  it("renders sections, span highlights, and facts when document and version ids are distinct", async () => {
    const markup = renderReader(DOC_10Q_ID, await readyData(DOC_10Q_ID));
    // Sections of the viewed filing render.
    expect(markup).toContain("Condensed Consolidated Statements of Operations");
    expect(markup).toContain("Item 2. Management&#x27;s Discussion and Analysis");
    // Span highlights render as citation buttons.
    expect(markup).toContain("span-mark");
    expect(markup).toContain("Cited source span:");
    // Facts of the viewed filing render in the panel (6 facts cite 10-Q spans).
    expect(markup).toContain("Extracted facts");
    expect(markup).toContain("(6 in this filing)");
    expect(markup).toContain("Diluted EPS");
    // The superseded banner links to the amendment.
    expect(markup).toContain("Superseded.");
    expect(markup).toContain(`/reader/${DOC_10QA_ID}`);
  });

  // Regression (finding 5): each document instance derives its own initial
  // state (outline selection) from its own sections; page.tsx keys the
  // component by documentId so navigation remounts with this fresh state.
  it("derives distinct initial reader state per document instance", async () => {
    const markup10q = renderReader(DOC_10Q_ID, await readyData(DOC_10Q_ID));
    const markup10qa = renderReader(DOC_10QA_ID, await readyData(DOC_10QA_ID));
    // Initial active outline entry is the first section of EACH document.
    expect(markup10q).toContain('aria-current="true"');
    expect(markup10qa).toContain('aria-current="true"');
    expect(markup10q).toContain("Part I — Financial Information");
    expect(markup10q).not.toContain("Explanatory Note");
    expect(markup10qa).toContain("Explanatory Note");
    expect(markup10qa).not.toContain("Part I — Financial Information");
  });

  // Regression (finding 7): absent period fields used to render as
  // "Period undefined to undefined".
  it("renders 'Period n/a' when period fields are absent", async () => {
    const data = await readyData(DOC_10Q_ID);
    const periodless: DocumentMeta[] = data.documents.map((doc) =>
      doc.id === DOC_10Q_ID ? { ...doc, period_start: undefined, period_end: undefined } : doc,
    );
    const markup = renderReader(DOC_10Q_ID, { ...data, documents: periodless });
    expect(markup).toContain("Period n/a");
    expect(markup).not.toContain("undefined");
  });

  // Regression (finding 2): failed citations must surface an explicit,
  // accessible error state in both the reader banner and the fact panel — and
  // the unverified quote must not render.
  it("surfaces a citation integrity error state instead of quoting a failed span", async () => {
    const data = await readyData(DOC_10Q_ID);
    // Fail the statements-revenue span (cited by the first revenue fact).
    const failedSpanId = data.spans.find(
      (span) => data.documentIdBySpanId[span.id] === DOC_10Q_ID,
    )!.id;
    const failedSpan = data.spans.find((span) => span.id === failedSpanId)!;
    const tampered: ReaderData = {
      ...data,
      spans: data.spans.filter((span) => span.id !== failedSpanId),
      integrityFailures: [
        {
          spanId: failedSpanId,
          sectionId: failedSpan.span.section_id,
          reason: "text_hash_mismatch",
        },
      ],
    };
    const markup = renderReader(DOC_10Q_ID, tampered);
    // Reader-level banner (role=alert carries it to assistive tech; the
    // warning glyph and explicit wording make it more than a color change).
    expect(markup).toContain("Citation integrity error.");
    expect(markup).toContain('role="alert"');
    // Fact-panel state names the failed check and withholds the quote.
    expect(markup).toContain("Citation integrity error:");
    expect(markup).toContain("does not match its recorded hash");
  });
});
