import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  MOCK_RERUN_ID,
  MOCK_RUN_ID,
  MOCK_TRACE,
} from "../lib/observatory/fixtures/synthetic-trace";
import { RunComparison } from "./RunComparison";

describe("RunComparison rendering", () => {
  it("names the comparison region with a heading and a captioned table", () => {
    const markup = renderToStaticMarkup(<RunComparison a={MOCK_TRACE} b={MOCK_TRACE} />);
    expect(markup).toContain('aria-labelledby="obs-compare-heading"');
    expect(markup).toContain('id="obs-compare-heading"');
    expect(markup).toContain("Run comparison");
    expect(markup).toContain("<caption");
    expect(markup).toContain('scope="row"');
  });

  it("identifies each run column by its short run id", () => {
    const other = { ...MOCK_TRACE, run_id: MOCK_RERUN_ID };
    const markup = renderToStaticMarkup(<RunComparison a={MOCK_TRACE} b={other} />);
    expect(markup).toContain(`Run A (${MOCK_RUN_ID.slice(0, 8)})`);
    expect(markup).toContain(`Run B (${MOCK_RERUN_ID.slice(0, 8)})`);
  });

  it("marks a changed metric for assistive tech without relying on colour alone", () => {
    const other = { ...MOCK_TRACE, cost_usd: "9.9999" };
    const markup = renderToStaticMarkup(<RunComparison a={MOCK_TRACE} b={other} />);
    expect(markup).toContain("obs-changed");
    expect(markup).toContain("9.9999");
    expect(markup).toContain("(changed)");
  });

  it("does not flag an unchanged metric as changed", () => {
    const markup = renderToStaticMarkup(<RunComparison a={MOCK_TRACE} b={MOCK_TRACE} />);
    expect(markup).not.toContain("(changed)");
  });
});
