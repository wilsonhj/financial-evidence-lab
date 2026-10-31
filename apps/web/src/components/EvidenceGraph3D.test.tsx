import { readFileSync } from "node:fs";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { findAll, findOne } from "../lib/test-support/shallow-tree";

const hooks = vi.hoisted(() => ({
  index: 0,
  values: [] as unknown[],
  effects: [] as (() => (() => void) | void)[],
}));

vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useId() {
    return "test-cutoff-id";
  },
  useMemo(factory: () => unknown) {
    return factory();
  },
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
  useRef(initial: unknown) {
    const i = hooks.index++;
    return (hooks.values[i] ??= { current: initial });
  },
  useEffect(effect: () => (() => void) | void) {
    hooks.effects.push(effect);
  },
}));

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

const props = (node: ReactElement) => node.props as Record<string, unknown>;

beforeEach(() => {
  hooks.index = 0;
  hooks.values = [];
  hooks.effects = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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
      scenario: "Bear",
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
    expect(filingNode?.state).toBe("fixture");
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

describe("fixture copy is not presented as evidence", () => {
  it("carries no made-up hashes and never says verified lineage", () => {
    for (const applied of [false, true]) {
      for (const decision of [null, DECISION_10Q, DECISION_CALL]) {
        const { nodes } = buildEpistemicGraph({
          scenario: "Base",
          source: decision?.sourceId ?? null,
          decision,
          approvals: COMPLETED_APPROVALS,
          applied,
          cutoffStep: 2,
        });
        for (const node of nodes) {
          const copy = `${node.sublabel} ${node.formulaOrHash}`;
          expect(copy, node.id).not.toMatch(/sha256/i);
          expect(copy, node.id).not.toMatch(/verified lineage/i);
          if (node.layer === "reported" || node.id === "calc-driver-arr") {
            expect(node.state, node.id).not.toBe("verified");
          }
        }
      }
    }
  });

  it("labels the applied, admissible view a fixture schematic in the inspector", () => {
    const markup = renderToStaticMarkup(
      <EvidenceGraph3D
        scenario="Base"
        source="sec-10q-nrr"
        decision={DECISION_10Q}
        approvals={COMPLETED_APPROVALS}
        applied
      />,
    );
    expect(markup).toContain("Illustrative fixture schematic");
    expect(markup).toContain("Staged in this session · fixture schematic");
    expect(markup).not.toContain("sha256=");
    expect(markup).not.toContain("sha256:");
    expect(markup).not.toContain("verified lineage");
  });

  it("shows Verified only for a gate the admissibility rule painted", () => {
    hooks.index = 0;
    const tree = EvidenceGraph3D({
      scenario: "Base",
      source: "sec-10q-nrr",
      decision: DECISION_10Q,
      approvals: COMPLETED_APPROVALS,
      applied: true,
    });
    const status = () =>
      props(findOne(tree, (e) => props(e)["data-testid"] === "text-viz3d-selected-status"))
        .children;
    expect(status()).toBe("Verified");
    const spanPill = findOne(
      tree,
      (e) => props(e)["data-testid"] === "button-viz3d-node-sec-10q-nrr",
    );
    (props(spanPill).onClick as () => void)();
    hooks.index = 0;
    const after = EvidenceGraph3D({
      scenario: "Base",
      source: "sec-10q-nrr",
      decision: DECISION_10Q,
      approvals: COMPLETED_APPROVALS,
      applied: true,
    });
    expect(
      props(findOne(after, (e) => props(e)["data-testid"] === "text-viz3d-selected-status"))
        .children,
    ).toBe("Fixture");
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

  it("drives the 3D canvas render loop, camera presets, pointer orbit/click, cutoff slider, and node pills", () => {
    const mockCtx = {
      clearRect: vi.fn(),
      createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
      createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
      fillRect: vi.fn(),
      strokeRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      closePath: vi.fn(),
      stroke: vi.fn(),
      fill: vi.fn(),
      arc: vi.fn(),
      setLineDash: vi.fn(),
      fillText: vi.fn(),
      measureText: vi.fn(() => ({ width: 48 })),
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 1,
      font: "",
    };

    const rafCallbacks: FrameRequestCallback[] = [];
    vi.stubGlobal("window", {
      matchMedia: () => ({ matches: false }),
      requestAnimationFrame: (cb: FrameRequestCallback) => {
        rafCallbacks.push(cb);
        return rafCallbacks.length;
      },
      cancelAnimationFrame: vi.fn(),
    });

    const onSelectNode = vi.fn();
    const tree = () => {
      hooks.index = 0;
      return EvidenceGraph3D({
        scenario: "Bull",
        source: "call-turn-48",
        decision: DECISION_CALL,
        approvals: COMPLETED_APPROVALS,
        applied: true,
        onSelectNode,
      });
    };

    tree();
    // Attach mock canvas to canvasRef (hook index 5)
    const canvasRef = hooks.values[5] as { current: unknown };
    canvasRef.current = {
      width: 680,
      height: 400,
      getContext: () => mockCtx,
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 680, height: 400 }),
    };

    // Run effect to draw 3D frame and schedule animation frame
    const cleanup = hooks.effects[0]?.();
    expect(mockCtx.clearRect).toHaveBeenCalled();
    expect(mockCtx.arc).toHaveBeenCalled();
    expect(rafCallbacks.length).toBeGreaterThan(0);
    cleanup?.();

    // Exercise preset buttons ("dag", "temporal", "constellation") and orbit toggle
    for (const presetId of ["dag", "temporal", "constellation"]) {
      const btn = findOne(
        tree(),
        (e) => props(e)["data-testid"] === `button-viz3d-preset-${presetId}`,
      );
      (props(btn).onClick as () => void)();
    }
    const orbitBtn = findOne(tree(), (e) => props(e)["data-testid"] === "button-viz3d-orbit");
    (props(orbitBtn).onClick as () => void)();

    // Exercise cutoff slider
    const slider = findOne(tree(), (e) => props(e)["data-testid"] === "input-viz3d-cutoff");
    (props(slider).onChange as (e: unknown) => void)({ target: { value: "0" } });
    const root = tree();
    // Re-run effect with cutoffStep = 0 so "cutoff-blocked" node colors are painted
    hooks.effects[hooks.effects.length - 1]?.();

    // Exercise node pill selection
    const gatePill = findOne(
      root,
      (e) => props(e)["data-testid"] === "button-viz3d-node-gate-c104",
    );
    (props(gatePill).onClick as () => void)();
    expect(onSelectNode).toHaveBeenCalledWith("gate-c104");

    const scenarioPill = findOne(
      tree(),
      (e) => props(e)["data-testid"] === "button-viz3d-node-calc-scenario",
    );
    (props(scenarioPill).onClick as () => void)();

    const spanPill = findOne(
      tree(),
      (e) => props(e)["data-testid"] === "button-viz3d-node-sec-10q-nrr",
    );
    (props(spanPill).onClick as () => void)();

    // Exercise canvas pointer drag and click hit-testing
    const canvasEl = findOne(tree(), (e) => props(e)["data-testid"] === "canvas-evidence-3d");
    const projectedRef = hooks.values[9] as {
      current: { id: string; sx: number; sy: number; r: number; depth: number }[];
    };
    const targetHit = projectedRef.current[0]!;
    (props(canvasEl).onClick as (e: unknown) => void)({
      clientX: targetHit.sx,
      clientY: targetHit.sy,
    });

    // Pointer drag gesture (> 4px suppresses click selection)
    (props(canvasEl).onPointerDown as (e: unknown) => void)({ clientX: 100, clientY: 100 });
    (props(canvasEl).onPointerMove as (e: unknown) => void)({ clientX: 120, clientY: 115 });
    (props(canvasEl).onPointerUp as () => void)();
    (props(canvasEl).onClick as (e: unknown) => void)({
      clientX: targetHit.sx,
      clientY: targetHit.sy,
    });
    (props(canvasEl).onPointerLeave as () => void)();
    expect(findAll(tree(), (e) => e.type === "button").length).toBeGreaterThan(5);
  });

  it("keeps every node and its label inside the canvas at each preset for any orbit yaw", () => {
    const ctx2d = new Proxy(
      { measureText: () => ({ width: 48 }) },
      {
        get: (target, key) =>
          key in target
            ? target[key as keyof typeof target]
            : key === "createLinearGradient" || key === "createRadialGradient"
              ? () => ({ addColorStop: () => undefined })
              : () => undefined,
        set: () => true,
      },
    );
    // Reduced motion paints exactly one frame and schedules no animation.
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    const width = 680;
    const height = 400;
    const tree = () => {
      hooks.index = 0;
      return EvidenceGraph3D({
        // Bull lifts the output node highest; the near L0 spans set the bottom.
        scenario: "Bull",
        source: null,
        decision: null,
        approvals: PENDING_APPROVALS,
        applied: false,
      });
    };
    tree();
    (hooks.values[5] as { current: unknown }).current = {
      width,
      height,
      getContext: () => ctx2d,
    };
    const orbitYawOffset = hooks.values[7] as { current: number };
    const projected = hooks.values[9] as {
      current: { id: string; sx: number; sy: number; r: number; depth: number }[];
    };

    for (const presetId of ["constellation", "dag", "temporal"]) {
      const btn = findOne(
        tree(),
        (e) => props(e)["data-testid"] === `button-viz3d-preset-${presetId}`,
      );
      (props(btn).onClick as () => void)();
      tree();
      const paint = hooks.effects[hooks.effects.length - 1]!;
      for (let step = 0; step < 24; step += 1) {
        orbitYawOffset.current = (step * Math.PI) / 12;
        paint();
        expect(projected.current).toHaveLength(11);
        for (const { id, sx, sy, r } of projected.current) {
          const where = `${presetId} yaw+${step}/24 ${id}`;
          // r is the hit radius (sphere + 6), which covers the selection ring;
          // the label pill ends 17px below it.
          expect(sy - r, where).toBeGreaterThanOrEqual(0);
          expect(sy + r + 17, where).toBeLessThanOrEqual(height);
          expect(sx - r, where).toBeGreaterThanOrEqual(0);
          expect(sx + r, where).toBeLessThanOrEqual(width);
        }
      }
    }
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
      const hasControlChar = [...content].some((ch) => {
        const code = ch.charCodeAt(0);
        return code < 32 && code !== 9 && code !== 10 && code !== 13;
      });
      expect(hasControlChar).toBe(false);
    }
  });
});
