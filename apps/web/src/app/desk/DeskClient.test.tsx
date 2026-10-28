import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { nrrStepLabel, ScenarioWaterfallChart } from "./DeskClient";
import type { ReviewDecision } from "./desk-state";

const decision = (sourceId: ReviewDecision["sourceId"]): ReviewDecision => ({
  conflictId: "C-104",
  sourceId,
  rationale: "test rationale",
});

describe("scenario waterfall is labelled as a fixture", () => {
  it("never shows a dollar effect for the NRR step, whichever source is selected", () => {
    const labels = [null, decision("sec-10q-nrr"), decision("call-turn-48")].map(nrrStepLabel);
    for (const label of labels) expect(label).not.toMatch(/\$/);
    expect(labels).toEqual(["NRR pending", "NRR 108% · 10-Q", "NRR 109% · Call"]);
  });

  it("does not claim a deterministic Decimal bridge", () => {
    for (const scenario of ["Base", "Bull", "Bear"]) {
      const markup = renderToStaticMarkup(
        <ScenarioWaterfallChart scenario={scenario} decision={decision("call-turn-48")} />,
      );
      expect(markup).toContain("Illustrative fixture");
      expect(markup).not.toContain("Deterministic Decimal Bridge");
      expect(markup).not.toContain("$60.4m");
      expect(markup).toContain("NRR 109% · Call");
    }
  });
});
