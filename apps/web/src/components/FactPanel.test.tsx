import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { fixtureEvidenceSource } from "../lib/data";
import { linkAmendments } from "../lib/amendments";
import { duplicateGroupIndex, groupDuplicateFacts } from "../lib/facts";
import { loadReaderData, type ReaderData } from "../lib/reader-loader";
import { DOC_10Q_ID } from "../lib/fixtures/synthetic-filing";
import { FactPanel, type FactPanelProps } from "./FactPanel";

async function readyData(documentId: string): Promise<ReaderData> {
  const result = await loadReaderData(fixtureEvidenceSource, documentId);
  if (result.kind !== "ready") throw new Error(`expected ready, got ${result.kind}`);
  return result.data;
}

function propsFor(data: ReaderData, overrides: Partial<FactPanelProps> = {}): FactPanelProps {
  const spansById = new Map(data.spans.map((record) => [record.id, record]));
  const sectionsById = new Map(data.sections.map((section) => [section.id, section]));
  const documentsById = new Map(data.documents.map((document) => [document.id, document]));
  const duplicateIndex = duplicateGroupIndex(groupDuplicateFacts(data.facts));
  return {
    facts: data.facts.filter(
      (record) => data.documentIdBySpanId[record.fact.source_span_id] === DOC_10Q_ID,
    ),
    spansById,
    sectionsById,
    documentsById,
    documentIdBySpanId: data.documentIdBySpanId,
    integrityFailureBySpanId: new Map(
      data.integrityFailures.map((failure) => [failure.spanId, failure]),
    ),
    duplicateIndex,
    amendmentLinks: linkAmendments(data.documents),
    selectedSpanId: null,
    ...overrides,
  };
}

describe("FactPanel rendering", () => {
  it("names the extracted-facts region and lists every fact of the filing", async () => {
    const data = await readyData(DOC_10Q_ID);
    const markup = renderToStaticMarkup(<FactPanel {...propsFor(data)} />);
    expect(markup).toContain('aria-label="Extracted facts"');
    expect(markup).toContain("Revenue");
    expect(markup).toContain("Diluted EPS");
    expect(markup).toContain(`(${propsFor(data).facts.length} in this filing)`);
  });

  it("shows the empty state when no fact matches the current selection", async () => {
    const data = await readyData(DOC_10Q_ID);
    const markup = renderToStaticMarkup(
      <FactPanel {...propsFor(data, { selectedSpanId: "cccccccc-0000-4000-8000-00000000dead" })} />,
    );
    expect(markup).toContain("No extracted facts for this selection.");
    expect(markup).toContain("(selected span)");
  });

  it("withholds the quote and surfaces an alert when a fact's citation failed integrity", async () => {
    const data = await readyData(DOC_10Q_ID);
    const failedSpanId = data.spans.find(
      (span) => data.documentIdBySpanId[span.id] === DOC_10Q_ID,
    )!.id;
    const props = propsFor(data, {
      integrityFailureBySpanId: new Map([
        [
          failedSpanId,
          { spanId: failedSpanId, sectionId: "irrelevant", reason: "text_hash_mismatch" as const },
        ],
      ]),
    });
    const markup = renderToStaticMarkup(<FactPanel {...props} />);
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Citation integrity error:");
    expect(markup).toContain("does not match its recorded hash");
  });

  it("flags a conflicting duplicate-fact group with the warning badge and a captioned comparison table", async () => {
    const data = await readyData(DOC_10Q_ID);
    const markup = renderToStaticMarkup(<FactPanel {...propsFor(data)} />);
    expect(markup).toContain("Inconsistent duplicate values");
    expect(markup).toContain("<caption");
    expect(markup).toContain('scope="col"');
  });

  it("flags a consistent duplicate-fact group without the warning badge", async () => {
    const data = await readyData(DOC_10Q_ID);
    const markup = renderToStaticMarkup(<FactPanel {...propsFor(data)} />);
    expect(markup).toContain("Duplicates consistent");
  });
});
