import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ObservatoryFlowViz } from "./ObservatoryFlowViz";
import { MOCK_ABSTAINED_TRACE, MOCK_TRACE } from "../lib/observatory/fixtures/synthetic-trace";

describe("ObservatoryFlowViz", () => {
  it("renders the 4 retrieval lanes, RRF k=60 nexus, supported/rejected counts, and budget meter", () => {
    const markup = renderToStaticMarkup(<ObservatoryFlowViz trace={MOCK_TRACE} />);
    expect(markup).toContain('data-testid="observatory-flow-viz"');
    expect(markup).toContain("Pipeline flow &amp; RRF fusion arena");
    expect(markup).toContain("RRF Fusion");
    expect(markup).toContain("k = 60");
    for (const lane of ["Dense", "Lexical", "Facts", "Tables"]) {
      expect(markup).toContain(lane);
    }
    expect(markup).toContain("Supported Set");
    expect(markup).toContain("Gate Rejected");
    expect(markup).toContain("Context budget utilization:");
    expect(markup).toContain("• 1 supported");
  });

  it("renders cleanly for an abstained trace with zero claims", () => {
    const markup = renderToStaticMarkup(<ObservatoryFlowViz trace={MOCK_ABSTAINED_TRACE} />);
    expect(markup).toContain("Claims (0)");
    expect(markup).toContain("• 0 supported");
  });
});
