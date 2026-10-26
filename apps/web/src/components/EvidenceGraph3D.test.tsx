import { readFileSync } from "node:fs";
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

const DECISION_CALL: ReviewDecision = {
  conflictId: "C-104",
  sourceId: "call-turn-48",
  rationale: "Earnings call transcript turn 48 reflects updated point-in-time NRR.",
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

  it("enforces point-in-time cutoff by blocking future-published nodes and decisions", () => {
    const atFiling = buildEpistemicGraph({
      scenario: "Base",
      source: "call-turn-48",
      decision: DECISION_CALL,
      approvals: COMPLETED_APPROVALS,
      applied: true,
      cutoffStep: 1,
    });
    const callNode = atFiling.nodes.find((n) => n.id === "call-turn-48");
    const filingNode = atFiling.nodes.find((n) => n.id === "sec-10q-nrr");
    const gateNode = atFiling.nodes.find((n) => n.id === "gate-c104");
    const outputNode = atFiling.nodes.find((n) => n.id === "output-fy27-rev");
    expect(callNode?.state).toBe("cutoff-blocked");
    expect(filingNode?.state).toBe("verified");
    // Because DECISION_CALL relies on call-turn-48 (step 2), it is inadmissible at step 1:
    expect(gateNode?.state).toBe("conflict");
    expect(outputNode?.state).toBe("pending");
    const gateToArrEdge = atFiling.edges.find(
      (e) => e.from === "gate-c104" && e.to === "calc-driver-arr",
    );
    expect(gateToArrEdge?.active).toBe(false);

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
    expect(
      preClose.edges.find((e) => e.from === "calc-scenario" && e.to === "output-fy27-rev")?.active,
    ).toBe(false);
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

  it("ships valid UTF-8 and control-character-free SVG architecture diagrams", () => {
    const svgFiles = [
      "../../../../docs/architecture/assets/system-overview.svg",
      "../../../../docs/architecture/assets/evidence-to-model-pipeline.svg",
      "../../../../docs/architecture/assets/hybrid-retrieval-and-extraction-fsm.svg",
      "../../../../docs/architecture/assets/calculation-dag-and-provenance.svg",
    ];
    for (const rel of svgFiles) {
      const content = readFileSync(new URL(rel, import.meta.url), "utf8");
      expect(content.startsWith("<svg")).toBe(true);
      expect(content.trimEnd().endsWith("</svg>")).toBe(true);
      // Ensure no raw control characters (ASCII < 32 except tab, LF, CR) exist
      const hasControlChar = [...content].some((ch) => {
        const code = ch.charCodeAt(0);
        return code < 32 && code !== 9 && code !== 10 && code !== 13;
      });
      expect(hasControlChar).toBe(false);
    }
  });
});
