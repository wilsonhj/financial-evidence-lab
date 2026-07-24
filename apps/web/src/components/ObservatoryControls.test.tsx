import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EventReplay } from "./EventReplay";
import { FeedbackControl } from "./FeedbackControl";
import { ObservatoryControls } from "./ObservatoryControls";
import { RunComparison } from "./RunComparison";
import { MOCK_RUN_ID, MOCK_TRACE } from "../lib/observatory/fixtures/synthetic-trace";

describe("ObservatoryControls", () => {
  it("renders bounded inputs within the contract ranges", () => {
    const markup = renderToStaticMarkup(<ObservatoryControls />);
    expect(markup).toContain('name="question"');
    expect(markup).toContain('maxLength="4000"');
    expect(markup).toContain('name="topK"');
    expect(markup).toContain('min="1"');
    expect(markup).toContain('max="100"');
    // All four lanes are offered.
    for (const lane of ["dense", "lexical", "facts", "tables"]) {
      expect(markup).toContain(`value="${lane}"`);
    }
  });

  it("shows a typed action-failure slug and threads a parent query id", () => {
    const markup = renderToStaticMarkup(
      <ObservatoryControls parentQueryId="q-1" error="invalid_scope" />,
    );
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("Action failed: invalid_scope");
    expect(markup).toContain('name="parentQueryId"');
    expect(markup).toContain('value="q-1"');
  });
});

describe("FeedbackControl", () => {
  it("offers the four contract feedback labels with a hidden item id", () => {
    const markup = renderToStaticMarkup(
      <FeedbackControl runId={MOCK_RUN_ID} itemId="10101010-0000-4000-8000-000000000001" />,
    );
    for (const label of ["relevant", "irrelevant", "duplicate", "temporally_invalid"]) {
      expect(markup).toContain(`value="${label}"`);
    }
    expect(markup).toContain('name="itemId"');
    expect(markup).toContain('name="runId"');
  });
});

describe("RunComparison", () => {
  it("renders metric rows and flags changed metrics for assistive tech", () => {
    const other = { ...MOCK_TRACE, cost_usd: "0.9999" };
    const markup = renderToStaticMarkup(<RunComparison a={MOCK_TRACE} b={other} />);
    expect(markup).toContain("Run comparison");
    expect(markup).toContain("Cost (USD)");
    expect(markup).toContain("0.9999");
    expect(markup).toContain("(changed)");
  });
});

describe("EventReplay", () => {
  it("renders the stored event log in seq order", () => {
    const markup = renderToStaticMarkup(<EventReplay trace={MOCK_TRACE} />);
    expect(markup).toContain("Stored replay");
    expect(markup).toContain("run_started");
    expect(markup).toContain("run_completed");
    expect(markup).toContain("#1");
  });
});
