import { describe, expect, it } from "vitest";

import { compareRuns } from "./compare";
import type { RetrievalTrace } from "./query-source";
import { MOCK_TRACE } from "./fixtures/synthetic-trace";

describe("compareRuns", () => {
  it("flags only the metrics that differ between two runs", () => {
    const cheaper: RetrievalTrace = { ...MOCK_TRACE, cost_usd: "0.0100", status: "abstained" };
    const rows = compareRuns(MOCK_TRACE, cheaper);
    const byLabel = new Map(rows.map((row) => [row.label, row]));
    expect(byLabel.get("Cost (USD)")?.changed).toBe(true);
    expect(byLabel.get("Status")?.changed).toBe(true);
    expect(byLabel.get("Claims")?.changed).toBe(false);
  });

  it("reports supported and rejected counts consistent with the integrity guard", () => {
    const rows = compareRuns(MOCK_TRACE, MOCK_TRACE);
    const supported = rows.find((row) => row.label === "Supported candidates");
    // Three fixture candidates are accepted and within cutoff.
    expect(supported?.a).toBe("3");
    expect(supported?.changed).toBe(false);
  });
});
