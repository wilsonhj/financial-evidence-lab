import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { buildEpistemicGraph, EvidenceGraph3D } from "./EvidenceGraph3D";
import type { GuidanceApproval, ReviewDecision } from "../app/desk/desk-state";

const PENDING_APPROVALS: GuidanceApproval[] = [
  { claimId: "C-109-revenue", approved: false },
  { claimId: "C-109-gross-margin", approved: false },
];

const COMPLETED_APPROVALS: GuidanceApproval[] = [
  { claimId: "C-109-revenue", approved: true },
  { claimId: "C-109-gross-margin", approved: true },
];

const DECISION_10Q: ReviewDecision = {
  conflictId: "C-104",
  sourceId: "sec-10q-nrr",
  rationale: "Filed 10-Q disclosure is the authoritative modeled metric.",
};

describe("buildEpistemicGraph", () => {
  it("marks C-104 as conflict before decision and verified once resolved", () => {
    const unresolved = buildEpistemicGraph({
      scenario: "Base",
      source: null,
      decision: null,
      approvals: PENDING_APPROVALS,
      applied: false,
      cutoffStep: 2,
    });
    const gateBefore = unresolved.nodes.find((n) => n.id === "gate-c104");
    expect(gateBefore?.state).toBe("conflict");

    const resolved = buildEpistemicGraph({
      scenario: "Bull",
      source: "sec-10q-nrr",
      decision: DECISION_10Q,
      approvals: COMPLETED_APPROVALS,
      applied: true,
      cutoffStep: 2,
    });
    const gateAfter = resolved.nodes.find((n) => n.id === "gate-c104");
    expect(gateAfter?.state).toBe("verified");
    const output = resolved.nodes.find((n) => n.id === "output-fy27-rev");
    expect(output?.label).toContain("$857.1m");
    expect(output?.state).toBe("verified");
  });

  it("enforces point-in-time cutoff by blocking future-published nodes", () => {
    const atFiling = buildEpistemicGraph({
      scenario: "Base",
      source: null,
      decision: null,
      approvals: PENDING_APPROVALS,
      applied: false,
      cutoffStep: 1,
    });
    const callNode = atFiling.nodes.find((n) => n.id === "call-turn-48");
    const filingNode = atFiling.nodes.find((n) => n.id === "sec-10q-nrr");
    expect(callNode?.state).toBe("cutoff-blocked");
    expect(filingNode?.state).toBe("verified");

    const preClose = buildEpistemicGraph({
      scenario: "Base",
      source: null,
      decision: null,
      approvals: PENDING_APPROVALS,
      applied: false,
      cutoffStep: 0,
    });
    expect(preClose.nodes.find((n) => n.id === "sec-10q-nrr")?.state).toBe("cutoff-blocked");
    expect(preClose.nodes.find((n) => n.id === "calc-scenario")?.state).toBe("override");
  });
});

describe("EvidenceGraph3D component", () => {
  it("renders the 3D canvas, camera preset controls, cutoff scrubber, and node inspector", () => {
    const markup = renderToStaticMarkup(
      <EvidenceGraph3D
        scenario="Base"
        source={null}
        decision={null}
        approvals={PENDING_APPROVALS}
        applied={false}
      />,
    );
    expect(markup).toContain('data-testid="evidence-graph-3d"');
    expect(markup).toContain('data-testid="canvas-evidence-3d"');
    expect(markup).toContain('data-testid="input-viz3d-cutoff"');
    expect(markup).toContain("3D Evidence &amp; Calculation Lineage Explorer");
    expect(markup).toContain("FY27 Revenue · $842.4m");
    expect(markup).toContain("C-104 conflict active");
  });
});
