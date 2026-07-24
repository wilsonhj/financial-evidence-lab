import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ObservatoryTrace } from "./ObservatoryTrace";
import { MOCK_QUERY_SNAPSHOT, MOCK_TRACE } from "../lib/observatory/fixtures/synthetic-trace";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// Version -> document map covering the fixture spans used by the mock trace.
const DOC_MAP = {
  "aaaaaaaa-0000-4000-8000-000000001001": "aaaaaaaa-0000-4000-8000-000000000001",
  "aaaaaaaa-0000-4000-8000-000000001002": "aaaaaaaa-0000-4000-8000-000000000002",
};

function render() {
  return renderToStaticMarkup(
    <ObservatoryTrace
      trace={MOCK_TRACE}
      snapshot={MOCK_QUERY_SNAPSHOT}
      documentIdByVersionId={DOC_MAP}
    />,
  );
}

describe("ObservatoryTrace", () => {
  it("renders the plan, variants, filters and the four retrieval lanes", () => {
    const markup = render();
    expect(markup).toContain("Query plan");
    expect(markup).toContain("fact_lookup");
    expect(markup).toContain(MOCK_QUERY_SNAPSHOT.question);
    expect(markup).toContain("Q1 2026 total revenue"); // variant
    expect(markup).toContain("10-Q"); // filter form
    for (const lane of ["Dense", "Lexical", "Facts", "Tables"]) {
      expect(markup).toContain(lane);
    }
  });

  it("renders raw, normalized, RRF and rerank ranks for candidates", () => {
    const markup = render();
    expect(markup).toContain("0.8123"); // raw score
    expect(markup).toContain("0.0164"); // rrf contribution
    expect(markup).toContain("0.9910"); // rerank score is present via candidate data
  });

  it("links a supported candidate to its exact reader span", () => {
    const markup = render();
    expect(markup).toContain(
      "/reader/aaaaaaaa-0000-4000-8000-000000000001?span=cccccccc-0000-4000-8000-000000000001",
    );
  });

  it("never renders future or cross-version evidence as supported", () => {
    const markup = render();
    // Both appear only as rejected, with their reason codes.
    expect(markup).toContain("temporal_after_cutoff");
    expect(markup).toContain("cross_version");
    // The rejected-candidates list is present.
    expect(markup).toContain("Rejected candidates");
  });

  it("renders claims with citation status and shows the contradiction distinctly", () => {
    const markup = render();
    expect(markup).toContain("Claims and citations");
    expect(markup).toContain("supported");
    expect(markup).toContain("contradicted");
    expect(markup).toContain("entailed");
  });

  it("renders budgets, latency and cost", () => {
    const markup = render();
    expect(markup).toContain("Budgets, latency and cost");
    expect(markup).toContain("0.0421"); // cost usd
    expect(markup).toContain("Latency: generate");
  });
});
