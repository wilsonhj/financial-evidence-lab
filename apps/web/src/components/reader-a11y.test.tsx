import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ReaderData } from "../lib/reader-loader";
import { fixtureEvidenceSource } from "../lib/data";
import { loadReaderData } from "../lib/reader-loader";
import { DOC_10Q_ID } from "../lib/fixtures/synthetic-filing";
import { EvidenceReader } from "./EvidenceReader";

// next/link needs a Next.js runtime context; render it as a plain anchor
// (same convention as EvidenceReader.test.tsx).
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

function renderReader(data: ReaderData): string {
  return renderToStaticMarkup(
    <EvidenceReader
      documentId={DOC_10Q_ID}
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

describe("Reader accessibility: landmarks", () => {
  it("exposes a distinct, labelled landmark for the outline, document, and evidence panel", async () => {
    const markup = renderReader(await readyData(DOC_10Q_ID));
    expect(markup).toContain('<nav class="outline-nav" aria-label="Filing outline"');
    expect(markup).toContain('id="main-content"');
    expect(markup).toContain('aria-label="Document reader"');
    expect(markup).toContain('<aside class="evidence-panel" aria-label="Evidence details"');
    // The document landmark's content is itself a labelled region distinct
    // from the surrounding <main>, not a second nested landmark of the same
    // kind announced twice.
    expect(markup).toContain('<article class="document-pane" aria-label="Filing content"');
  });

  it("labels the facts and notes regions inside the evidence panel", async () => {
    const markup = renderReader(await readyData(DOC_10Q_ID));
    expect(markup).toContain('aria-label="Extracted facts"');
    expect(markup).toContain('aria-label="Analyst notes"');
  });

  it("names the outline list via its own heading, not a bare landmark label", async () => {
    const markup = renderReader(await readyData(DOC_10Q_ID));
    expect(markup).toContain('id="outline-heading"');
    expect(markup).toContain('aria-labelledby="outline-heading"');
  });
});

// WCAG 2.2 SC 4.1.3 (Status Messages), audited in ACCESSIBILITY.md: adding
// or removing an analyst note is a client-side state change with no page
// navigation and no focus move, so NotesPanel carries a visually-hidden
// role="status" live region announcing the outcome.
describe("Reader accessibility: status messages", () => {
  it("carries a visually-hidden role=status live region for note add/remove outcomes", async () => {
    const markup = renderReader(await readyData(DOC_10Q_ID));
    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-live="polite"');
  });
});

describe("Reader accessibility: the integrity alert", () => {
  it("surfaces a citation-integrity failure as an alert-role region, not a silently dropped citation", async () => {
    const data = await readyData(DOC_10Q_ID);
    const failedSpan = data.spans.find((span) => data.documentIdBySpanId[span.id] === DOC_10Q_ID)!;
    const tampered: ReaderData = {
      ...data,
      spans: data.spans.filter((span) => span.id !== failedSpan.id),
      integrityFailures: [
        {
          spanId: failedSpan.id,
          sectionId: failedSpan.span.section_id,
          reason: "text_hash_mismatch",
        },
      ],
    };
    const markup = renderReader(tampered);
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Citation integrity error.");
    // A colour-only cue is never the sole signal: the glyph is decorative
    // (aria-hidden) and the wording carries the meaning.
    expect(markup).toContain('aria-hidden="true"');
  });

  it("stays silent (no alert) when every citation verifies", async () => {
    const data = await readyData(DOC_10Q_ID);
    expect(data.integrityFailures).toEqual([]);
    const markup = renderReader(data);
    expect(markup).not.toContain('role="alert"');
  });
});

describe("Reader accessibility: keyboard operability of span selection", () => {
  it("renders every cited span as a real <button>, natively focusable and Enter/Space-activatable", async () => {
    const data = await readyData(DOC_10Q_ID);
    const markup = renderReader(data);
    // A real <button> (not a styled <div>/<span> with a click handler) gets
    // native keyboard focus and Enter/Space activation from the browser with
    // no bespoke key handling required.
    expect(markup).toContain('<button type="button" class="span-mark"');
    // It is reachable by assistive tech as a citation control, not plain text.
    expect(markup).toContain("Cited source span:");
  });

  it("conveys the selected span with aria-pressed, an aria-current equivalent for a toggle control", async () => {
    const data = await readyData(DOC_10Q_ID);
    const spanId = "cccccccc-0000-4000-8000-000000000001";
    const markup = renderToStaticMarkup(
      <EvidenceReader
        documentId={DOC_10Q_ID}
        documents={data.documents}
        sections={data.sections}
        spans={data.spans}
        facts={data.facts}
        documentIdBySectionId={data.documentIdBySectionId}
        documentIdBySpanId={data.documentIdBySpanId}
        integrityFailures={data.integrityFailures}
        initialSpanId={spanId}
      />,
    );
    expect(markup).toContain('aria-pressed="true"');
    expect(markup).toContain('aria-pressed="false"');
  });

  it("never renders a citation span as a non-interactive element", async () => {
    const data = await readyData(DOC_10Q_ID);
    const markup = renderReader(data);
    // Every occurrence of the citation glyph is inside a real button, never a
    // bare span/div standing in for one.
    const glyphCount = (markup.match(/span-glyph/g) ?? []).length;
    const citedButtonCount = (markup.match(/Cited source span:/g) ?? []).length;
    expect(glyphCount).toBe(citedButtonCount);
    expect(citedButtonCount).toBeGreaterThan(0);
  });
});
