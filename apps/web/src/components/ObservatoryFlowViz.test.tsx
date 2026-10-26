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

import { ObservatoryFlowViz } from "./ObservatoryFlowViz";
import { MOCK_ABSTAINED_TRACE, MOCK_TRACE } from "../lib/observatory/fixtures/synthetic-trace";

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
