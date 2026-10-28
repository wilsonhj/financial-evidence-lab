import type { ReactElement, ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { findOne } from "../lib/test-support/shallow-tree";

const hooks = vi.hoisted(() => ({
  index: 0,
  values: [] as unknown[],
}));

vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useState(initial: unknown) {
    const i = hooks.index++;
    if (!Object.hasOwn(hooks.values, i))
      hooks.values[i] = typeof initial === "function" ? initial() : initial;
    return [
      hooks.values[i],
      (next: unknown) => {
        hooks.values[i] = typeof next === "function" ? next(hooks.values[i]) : next;
      },
    ];
  },
}));

import { ObservatoryFlowViz, rejectionSummary } from "./ObservatoryFlowViz";
import { MOCK_ABSTAINED_TRACE, MOCK_TRACE } from "../lib/observatory/fixtures/synthetic-trace";
import { partitionCandidates, type RejectedCandidate } from "../lib/observatory/trace-view";

const props = (node: ReactElement) => node.props as Record<string, unknown>;

beforeEach(() => {
  hooks.index = 0;
  hooks.values = [];
});

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

  it("summarizes the rejection codes the trace carries instead of a fixed label", () => {
    const { rejected } = partitionCandidates(MOCK_TRACE);
    const codes = rejected.map((item) => item.code);
    expect(codes).toEqual(["dedupe_near_duplicate", "temporal_after_cutoff", "cross_version"]);
    const summary = rejectionSummary(rejected);
    for (const code of codes) expect(summary.full).toContain(code);
    expect(summary.short).toBe("dedupe, cutoff, version");
    const markup = renderToStaticMarkup(<ObservatoryFlowViz trace={MOCK_TRACE} />);
    expect(markup).not.toContain("Future / cross-version");
    expect(markup).toContain(`Rejection codes: ${summary.full}`);
    expect(markup).toContain("dedupe, cutoff, version");
    expect(rejectionSummary([])).toEqual({ short: "none", full: "No candidates rejected" });
  });

  it("truncates the short rejection summary once more than three codes are present", () => {
    const rejected = [
      "temporal_after_cutoff",
      "cross_version",
      "dedupe_near_duplicate",
      "budget_overflow",
    ].map((code) => ({ code }) as RejectedCandidate);
    expect(rejectionSummary(rejected)).toEqual({
      short: "cutoff, version +2 more",
      full: "temporal_after_cutoff, cross_version, dedupe_near_duplicate, budget_overflow",
    });
  });

  it("renders cleanly for an abstained trace with zero claims", () => {
    const markup = renderToStaticMarkup(<ObservatoryFlowViz trace={MOCK_ABSTAINED_TRACE} />);
    expect(markup).toContain("Claims (0)");
    expect(markup).toContain("• 0 supported");
  });

  it("supports interactive lane filtering and toggling back to all lanes", () => {
    const tree = (): ReactNode => {
      hooks.index = 0;
      return ObservatoryFlowViz({ trace: MOCK_TRACE });
    };

    const denseBtn = findOne(
      tree(),
      (e) => props(e)["data-testid"] === "button-obs-flow-lane-dense",
    );
    (props(denseBtn).onClick as () => void)();

    const summaryBadge = findOne(
      tree(),
      (e) => props(e)["data-testid"] === "obs-flow-selected-lane-summary",
    );
    expect(String(props(summaryBadge).children)).toContain("Dense");

    // Clicking the same lane again toggles back to null
    const denseBtnAgain = findOne(
      tree(),
      (e) => props(e)["data-testid"] === "button-obs-flow-lane-dense",
    );
    (props(denseBtnAgain).onClick as () => void)();

    // Clicking Tables then All lanes resets filter
    const tablesBtn = findOne(
      tree(),
      (e) => props(e)["data-testid"] === "button-obs-flow-lane-tables",
    );
    (props(tablesBtn).onClick as () => void)();
    const allBtn = findOne(tree(), (e) => props(e)["data-testid"] === "button-obs-flow-lane-all");
    (props(allBtn).onClick as () => void)();
    expect(hooks.values[0]).toBeNull();
  });
});
