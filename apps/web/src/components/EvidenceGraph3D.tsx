"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { EvidenceSourceId, GuidanceApproval, ReviewDecision } from "../app/desk/desk-state";

export type CameraPreset = "constellation" | "dag" | "temporal";
export type ProvenanceLayer = "reported" | "extraction" | "calculation" | "output";
export type NodeState = "verified" | "conflict" | "pending" | "override" | "cutoff-blocked";

export interface GraphNode3D {
  id: string;
  label: string;
  sublabel: string;
  layer: ProvenanceLayer;
  x: number;
  y: number;
  z: number;
  publishedStep: 0 | 1 | 2;
  publishedAt: string;
  formulaOrHash: string;
  state: NodeState;
}

export interface GraphEdge3D {
  from: string;
  to: string;
  active: boolean;
  kind: "provenance" | "conflict" | "scenario" | "iteration";
}

export interface CutoffStop {
  step: 0 | 1 | 2;
  iso: string;
  label: string;
  description: string;
}

export const CUTOFF_STOPS: readonly CutoffStop[] = [
  {
    step: 0,
    iso: "2026-07-31T23:59:00Z",
    label: "Q2 Close (2026-07-31)",
    description: "Both Q2 10-Q and Earnings Call are in the future (blocked by cutoff).",
  },
  {
    step: 1,
    iso: "2026-08-14T16:15:00Z",
    label: "10-Q Filed (16:15 UTC)",
    description: "10-Q spans are visible; Earnings Call (17:30 UTC) is fenced out by cutoff.",
  },
  {
    step: 2,
    iso: "2026-08-14T18:00:00Z",
    label: "Post-Call (18:00 UTC)",
    description:
      "All Q2 10-Q and Earnings Call evidence spans satisfy published_at <= effective_as_of.",
  },
];

export interface EvidenceGraph3DProps {
  scenario: string;
  source: EvidenceSourceId | null;
  decision: ReviewDecision | null;
  approvals: GuidanceApproval[];
  applied: boolean;
  onSelectNode?: (nodeId: string) => void;
}

function presetAngles(preset: CameraPreset): { yaw: number; pitch: number } {
  switch (preset) {
    case "constellation":
      return { yaw: 0.48, pitch: 0.32 };
    case "dag":
      return { yaw: 0.0, pitch: 0.08 };
    case "temporal":
      return { yaw: -1.15, pitch: 0.22 };
    default: {
      const _never: never = preset;
      return _never;
    }
  }
}

function nodeColor(state: NodeState): { fill: string; ring: string; badge: string } {
  switch (state) {
    case "verified":
      return { fill: "#2ea043", ring: "#56d364", badge: "Verified" };
    case "conflict":
      return { fill: "#d29922", ring: "#f0c96f", badge: "Conflict / Gate" };
    case "pending":
      return { fill: "#388bfd", ring: "#79c0ff", badge: "Pending Review" };
    case "override":
      return { fill: "#a371f7", ring: "#d2a8ff", badge: "Scenario / Calc" };
    case "cutoff-blocked":
      return { fill: "#da3633", ring: "#ff7b72", badge: "Blocked (Future)" };
    default: {
      const _never: never = state;
      return _never;
    }
  }
}

function layerTitle(layer: ProvenanceLayer): string {
  switch (layer) {
    case "reported":
      return "L0 · Immutable Source Spans";
    case "extraction":
      return "L1 · Extraction & Review Gates";
    case "calculation":
      return "L2 · Decimal Calc DAG & Scenarios";
    case "output":
      return "L3 · Reported Financial Output";
    default: {
      const _never: never = layer;
      return _never;
    }
  }
}

export function buildEpistemicGraph(props: {
  scenario: string;
  source: EvidenceSourceId | null;
  decision: ReviewDecision | null;
  approvals: GuidanceApproval[];
  applied: boolean;
  cutoffStep: 0 | 1 | 2;
}): { nodes: GraphNode3D[]; edges: GraphEdge3D[] } {
  const { scenario, source, decision, approvals, applied, cutoffStep } = props;
  const revApproved = approvals.find((a) => a.claimId === "C-109-revenue")?.approved ?? false;
  const gmApproved = approvals.find((a) => a.claimId === "C-109-gross-margin")?.approved ?? false;
  const effectiveSource = decision?.sourceId ?? source;

  const revenueByScenario: Record<string, string> = {
    Base: "$842.4m",
    Bull: "$857.1m",
    Bear: "$823.8m",
  };
  const scenarioDeltaByScenario: Record<string, string> = {
    Base: "+0.0% Base",
    Bull: "+$14.7m (+1.7%)",
    Bear: "-$18.6m (-2.2%)",
  };

  const rawNodes: Omit<GraphNode3D, "state">[] = [
    {
      id: "sec-10q-nrr",
      label: "10-Q Span · NRR 108%",
      sublabel: "Page 34 · sha256:9f4b..8a0",
      layer: "reported",
      x: -170,
      y: 112,
      z: -60,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "start_char=48120..48192 · sha256=9f4b8a0e",
    },
    {
      id: "call-turn-48",
      label: "Call Turn 48 · NRR 109%",
      sublabel: "Transcript · sha256:c25e..27b",
      layer: "reported",
      x: -58,
      y: 112,
      z: 65,
      publishedStep: 2,
      publishedAt: "2026-08-14T17:30:00Z",
      formulaOrHash: "turn=48 · sha256=c25e27b4",
    },
    {
      id: "sec-10q-guidance",
      label: "10-Q Span · Guidance",
      sublabel: "Page 42 · $790–794m",
      layer: "reported",
      x: 62,
      y: 112,
      z: -45,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "start_char=61004..61118 · sha256=75fad38c",
    },
    {
      id: "sec-10q-actuals",
      label: "10-Q Fact · ARR $782m",
      sublabel: "Page 12 · XBRL us-gaap",
      layer: "reported",
      x: 174,
      y: 112,
      z: 50,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "fact_id=arr-2026q2 · scale=10^6",
    },
    {
      id: "gate-c104",
      label: decision
        ? `C-104 Resolved (${decision.sourceId === "sec-10q-nrr" ? "108%" : "109%"})`
        : "C-104 NRR Conflict",
      sublabel: decision ? "Human rationale recorded" : "10-Q 108% vs Call 109%",
      layer: "extraction",
      x: -115,
      y: 36,
      z: 10,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "comparability_key=nrr:usd:trailing_12m",
    },
    {
      id: "gate-c109-rev",
      label: "C-109 Revenue Range",
      sublabel: revApproved ? "Approved ($790–794m)" : "Pending ($790–794m)",
      layer: "extraction",
      x: 24,
      y: 36,
      z: -35,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "low=790000000 · high=794000000 · USD",
    },
    {
      id: "gate-c109-gm",
      label: "C-109 Gross Margin",
      sublabel: gmApproved ? "Approved (76.0–76.5%)" : "Pending (76.0–76.5%)",
      layer: "extraction",
      x: 145,
      y: 36,
      z: 30,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "low=0.760 · high=0.765 · ratio",
    },
    {
      id: "calc-driver-arr",
      label: "OperationalDriver · ARR",
      sublabel: "Retention + Expansion",
      layer: "calculation",
      x: -105,
      y: -44,
      z: -25,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "[arr_q2] * [nrr_authoritative]",
    },
    {
      id: "calc-jacobi-scc",
      label: "Jacobi SCC · 5 Sweeps",
      sublabel: "Convergence tol <= 0.01",
      layer: "calculation",
      x: 18,
      y: -44,
      z: 45,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "IterationGroup(max_iterations=100, sweeps=5)",
    },
    {
      id: "calc-scenario",
      label: `ScenarioOverride · ${scenario}`,
      sublabel: scenarioDeltaByScenario[scenario] ?? "+0.0%",
      layer: "calculation",
      x: 142,
      y: -44,
      z: -20,
      publishedStep: 0,
      publishedAt: "2026-07-31T23:59:00Z",
      formulaOrHash: `Scenario(id="${scenario.toLowerCase()}", model="v19")`,
    },
    {
      id: "output-fy27-rev",
      label: `FY27 Revenue · ${revenueByScenario[scenario] ?? "$842.4m"}`,
      sublabel: applied ? "Staged with verified lineage" : "Preview · awaiting review gates",
      layer: "output",
      x: 12,
      y: -118,
      z: 0,
      publishedStep: 1,
      publishedAt: "2026-08-14T16:05:00Z",
      formulaOrHash: "ReportedFinancialOutputNode(unit=USD, quantum=0.01)",
    },
  ];

  const nodes: GraphNode3D[] = rawNodes.map((n) => {
    if (n.publishedStep > cutoffStep) {
      return { ...n, state: "cutoff-blocked" };
    }
    if (n.id === "gate-c104") {
      return { ...n, state: decision ? "verified" : "conflict" };
    }
    if (n.id === "gate-c109-rev") {
      return { ...n, state: revApproved ? "verified" : "pending" };
    }
    if (n.id === "gate-c109-gm") {
      return { ...n, state: gmApproved ? "verified" : "pending" };
    }
    if (n.id === "calc-scenario" || n.id === "calc-jacobi-scc") {
      return { ...n, state: "override" };
    }
    if (n.id === "output-fy27-rev") {
      return { ...n, state: applied ? "verified" : "pending" };
    }
    return { ...n, state: "verified" };
  });

  const edges: GraphEdge3D[] = [
    {
      from: "sec-10q-nrr",
      to: "gate-c104",
      active: cutoffStep >= 1 && (effectiveSource === null || effectiveSource === "sec-10q-nrr"),
      kind: decision?.sourceId === "sec-10q-nrr" ? "provenance" : "conflict",
    },
    {
      from: "call-turn-48",
      to: "gate-c104",
      active: cutoffStep >= 2 && (effectiveSource === null || effectiveSource === "call-turn-48"),
      kind: decision?.sourceId === "call-turn-48" ? "provenance" : "conflict",
    },
    {
      from: "sec-10q-guidance",
      to: "gate-c109-rev",
      active: cutoffStep >= 1,
      kind: "provenance",
    },
    {
      from: "sec-10q-guidance",
      to: "gate-c109-gm",
      active: cutoffStep >= 1,
      kind: "provenance",
    },
    {
      from: "sec-10q-actuals",
      to: "calc-driver-arr",
      active: cutoffStep >= 1,
      kind: "provenance",
    },
    {
      from: "gate-c104",
      to: "calc-driver-arr",
      active: cutoffStep >= 1 && decision !== null,
      kind: "provenance",
    },
    {
      from: "gate-c109-rev",
      to: "calc-jacobi-scc",
      active: cutoffStep >= 1 && revApproved,
      kind: "iteration",
    },
    {
      from: "gate-c109-gm",
      to: "calc-jacobi-scc",
      active: cutoffStep >= 1 && gmApproved,
      kind: "iteration",
    },
    {
      from: "calc-driver-arr",
      to: "output-fy27-rev",
      active: cutoffStep >= 1,
      kind: "provenance",
    },
    {
      from: "calc-jacobi-scc",
      to: "output-fy27-rev",
      active: cutoffStep >= 1 && revApproved && gmApproved,
      kind: "iteration",
    },
    {
      from: "calc-scenario",
      to: "output-fy27-rev",
      active: true,
      kind: "scenario",
    },
  ];

  return { nodes, edges };
}

export function EvidenceGraph3D({
  scenario,
  source,
  decision,
  approvals,
  applied,
  onSelectNode,
}: EvidenceGraph3DProps) {
  const [preset, setPreset] = useState<CameraPreset>("constellation");
  const [cutoffStep, setCutoffStep] = useState<0 | 1 | 2>(2);
  const [selectedId, setSelectedId] = useState<string>("output-fy27-rev");
  const [autoOrbit, setAutoOrbit] = useState<boolean>(true);
  const [angles, setAngles] = useState<{ yaw: number; pitch: number }>(() =>
    presetAngles("constellation"),
  );

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragRef = useRef<{ active: boolean; lastX: number; lastY: number }>({
    active: false,
    lastX: 0,
    lastY: 0,
  });
  const projectedRef = useRef<{ id: string; sx: number; sy: number; r: number; depth: number }[]>(
    [],
  );

  const { nodes, edges } = useMemo(
    () =>
      buildEpistemicGraph({
        scenario,
        source,
        decision,
        approvals,
        applied,
        cutoffStep,
      }),
    [scenario, source, decision, approvals, applied, cutoffStep],
  );

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedId) ?? nodes[nodes.length - 1]!,
    [nodes, selectedId],
  );

  const cutoffInfo = CUTOFF_STOPS[cutoffStep] ?? CUTOFF_STOPS[2]!;
  const blockedCount = nodes.filter((n) => n.state === "cutoff-blocked").length;
  const verifiedCount = nodes.filter((n) => n.state === "verified").length;

  const choosePreset = (next: CameraPreset) => {
    setPreset(next);
    setAngles(presetAngles(next));
  };

  const selectNode = (id: string) => {
    setSelectedId(id);
    onSelectNode?.(id);
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let frameId = 0;
    let pulsePhase = 0;
    const reducedMotion =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const renderFrame = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      // Deep space / epistemic grid background
      const grad = ctx.createLinearGradient(0, 0, 0, height);
      grad.addColorStop(0, "#080e1a");
      grad.addColorStop(1, "#0f192c");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);

      // Draw subtle horizontal layer planes
      const layerY = [-118, -44, 36, 112];
      const layerLabels = [
        "L3 · REPORTED OUTPUT",
        "L2 · DECIMAL CALC DAG",
        "L1 · EXTRACTION & REVIEW",
        "L0 · SOURCE SPANS",
      ];

      const yaw = angles.yaw + (autoOrbit && !reducedMotion ? pulsePhase * 0.18 : 0);
      const pitch = angles.pitch;
      const cosY = Math.cos(yaw);
      const sinY = Math.sin(yaw);
      const cosP = Math.cos(pitch);
      const sinP = Math.sin(pitch);
      const fov = 440;
      const viewerDist = 420;

      const project = (x: number, y: number, z: number) => {
        const rx = x * cosY - z * sinY;
        const rz = x * sinY + z * cosY;
        const ry = y * cosP - rz * sinP;
        const rz2 = y * sinP + rz * cosP;
        const scale = fov / Math.max(120, viewerDist + rz2);
        return {
          sx: width / 2 + rx * scale,
          sy: height / 2 + ry * scale,
          scale,
          depth: rz2,
        };
      };

      // Draw 3D floor/layer rings
      layerY.forEach((ly, idx) => {
        ctx.save();
        ctx.strokeStyle = "rgba(88, 166, 255, 0.13)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        const corners = [
          project(-210, ly, -95),
          project(210, ly, -95),
          project(210, ly, 95),
          project(-210, ly, 95),
        ];
        ctx.moveTo(corners[0]!.sx, corners[0]!.sy);
        corners.slice(1).forEach((c) => ctx.lineTo(c.sx, c.sy));
        ctx.closePath();
        ctx.stroke();

        ctx.fillStyle = "rgba(139, 148, 158, 0.55)";
        ctx.font = "600 10px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
        ctx.fillText(layerLabels[idx] ?? "", corners[0]!.sx + 6, corners[0]!.sy - 4);
        ctx.restore();
      });

      const nodeMap = new Map(
        nodes.map((node) => {
          const p = project(node.x, node.y, node.z);
          return [node.id, { node, ...p }];
        }),
      );

      // Draw edges and animated provenance pulses
      edges.forEach((edge) => {
        const from = nodeMap.get(edge.from);
        const to = nodeMap.get(edge.to);
        if (!from || !to) return;

        ctx.save();
        ctx.beginPath();
        ctx.moveTo(from.sx, from.sy);
        ctx.lineTo(to.sx, to.sy);
        if (!edge.active) {
          ctx.strokeStyle = "rgba(139, 148, 158, 0.24)";
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = 1.2;
        } else if (edge.kind === "conflict") {
          ctx.strokeStyle = "rgba(210, 153, 34, 0.78)";
          ctx.lineWidth = 2;
        } else if (edge.kind === "scenario") {
          ctx.strokeStyle = "rgba(163, 113, 247, 0.85)";
          ctx.lineWidth = 2.2;
        } else {
          ctx.strokeStyle = "rgba(63, 185, 80, 0.82)";
          ctx.lineWidth = 2.2;
        }
        ctx.stroke();

        // Animated energy pulse along active edges
        if (edge.active) {
          const t = (pulsePhase * 0.9) % 1;
          const px = from.sx + (to.sx - from.sx) * t;
          const py = from.sy + (to.sy - from.sy) * t;
          ctx.beginPath();
          ctx.arc(px, py, 3.4, 0, Math.PI * 2);
          ctx.fillStyle = edge.kind === "conflict" ? "#f0c96f" : "#79c0ff";
          ctx.fill();
        }
        ctx.restore();
      });

      // Sort nodes back-to-front (Painter's algorithm)
      const sorted = [...nodeMap.values()].sort((a, b) => b.depth - a.depth);
      const hitList: { id: string; sx: number; sy: number; r: number; depth: number }[] = [];

      sorted.forEach(({ node, sx, sy, scale, depth }) => {
        const palette = nodeColor(node.state);
        const isSelected = node.id === selectedId;
        const radius = Math.max(9, (node.layer === "output" ? 16 : 12) * scale);
        hitList.push({ id: node.id, sx, sy, r: radius + 6, depth });

        ctx.save();
        // Outer halo for selected or conflict node
        if (isSelected || node.state === "conflict" || node.state === "cutoff-blocked") {
          ctx.beginPath();
          ctx.arc(sx, sy, radius + (isSelected ? 6 : 4), 0, Math.PI * 2);
          ctx.strokeStyle = palette.ring;
          ctx.lineWidth = isSelected ? 2.5 : 1.4;
          ctx.stroke();
        }

        // 3D sphere shading
        const sphereGrad = ctx.createRadialGradient(
          sx - radius * 0.3,
          sy - radius * 0.3,
          radius * 0.15,
          sx,
          sy,
          radius,
        );
        sphereGrad.addColorStop(0, palette.ring);
        sphereGrad.addColorStop(1, palette.fill);

        ctx.beginPath();
        ctx.arc(sx, sy, radius, 0, Math.PI * 2);
        ctx.fillStyle = sphereGrad;
        ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = "#0b1220";
        ctx.stroke();

        // Node label pill
        ctx.font = `${isSelected ? "700" : "600"} 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`;
        const textWidth = ctx.measureText(node.label).width;
        const pillX = sx - textWidth / 2 - 6;
        const pillY = sy + radius + 5;
        ctx.fillStyle = isSelected ? "rgba(23, 94, 203, 0.92)" : "rgba(13, 18, 28, 0.84)";
        ctx.fillRect(pillX, pillY, textWidth + 12, 18);
        ctx.strokeStyle = isSelected ? "#79c0ff" : "rgba(139, 148, 158, 0.35)";
        ctx.lineWidth = 1;
        ctx.strokeRect(pillX, pillY, textWidth + 12, 18);

        ctx.fillStyle = "#f0f6fc";
        ctx.fillText(node.label, sx - textWidth / 2, pillY + 13);
        ctx.restore();
      });

      projectedRef.current = hitList;

      if (!reducedMotion) {
        pulsePhase += 0.016;
        frameId = window.requestAnimationFrame(renderFrame);
      }
    };

    renderFrame();
    return () => {
      if (frameId) window.cancelAnimationFrame(frameId);
    };
  }, [nodes, edges, angles, autoOrbit, selectedId]);

  const handleCanvasClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / Math.max(1, rect.width);
    const scaleY = canvas.height / Math.max(1, rect.height);
    const x = (event.clientX - rect.left) * scaleX;
    const y = (event.clientY - rect.top) * scaleY;

    // Pick closest frontmost node within hit radius
    const hits = projectedRef.current
      .filter((item) => Math.hypot(item.sx - x, item.sy - y) <= item.r)
      .sort((a, b) => a.depth - b.depth);
    if (hits[0]) {
      selectNode(hits[0].id);
    }
  };

  return (
    <section
      className="viz3d-card"
      data-testid="evidence-graph-3d"
      aria-label="3D Evidence and Calculation Lineage Constellation"
    >
      <div className="viz3d-header">
        <div>
          <p className="eyebrow">Spatial Epistemic Graph · 4-Layer Provenance DAG</p>
          <h3>3D Evidence &amp; Calculation Lineage Explorer</h3>
        </div>
        <div className="viz3d-controls" role="group" aria-label="3D camera presets">
          {(
            [
              ["constellation", "3D Orbit"],
              ["dag", "Layered DAG"],
              ["temporal", "Cutoff Slice"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              data-testid={`button-viz3d-preset-${id}`}
              aria-pressed={preset === id}
              onClick={() => choosePreset(id)}
            >
              {label}
            </button>
          ))}
          <button
            type="button"
            data-testid="button-viz3d-orbit"
            aria-pressed={autoOrbit}
            onClick={() => setAutoOrbit((prev) => !prev)}
          >
            {autoOrbit ? "Pause Orbit" : "Auto Orbit"}
          </button>
        </div>
      </div>

      <div className="viz3d-hud-bar" role="status" aria-live="polite">
        <span>
          <b>Verified nodes:</b> {verifiedCount} / {nodes.length}
        </span>
        <span>
          <b>Cutoff blocked:</b> {blockedCount}
        </span>
        <span>
          <b>Active scenario:</b> {scenario}
        </span>
        <span>
          <b>Lineage state:</b>{" "}
          {applied
            ? "All gates unlocked"
            : decision
              ? "NRR resolved · awaiting guidance"
              : "C-104 conflict active"}
        </span>
      </div>

      <div className="viz3d-canvas-wrap">
        <canvas
          ref={canvasRef}
          width={680}
          height={330}
          className="viz3d-canvas"
          data-testid="canvas-evidence-3d"
          onClick={handleCanvasClick}
          onPointerDown={(e) => {
            dragRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
          }}
          onPointerMove={(e) => {
            if (!dragRef.current.active) return;
            const dx = e.clientX - dragRef.current.lastX;
            const dy = e.clientY - dragRef.current.lastY;
            dragRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
            setAngles((prev) => ({
              yaw: prev.yaw + dx * 0.01,
              pitch: Math.max(-0.85, Math.min(0.85, prev.pitch + dy * 0.01)),
            }));
          }}
          onPointerUp={() => {
            dragRef.current.active = false;
          }}
          onPointerLeave={() => {
            dragRef.current.active = false;
          }}
          aria-label="Interactive 3D canvas of filing spans, review gates, calculation nodes, and FY27 revenue output"
        />
      </div>

      <div className="viz3d-scrubber">
        <label htmlFor="viz3d-cutoff-range">
          <span>
            Point-in-time cutoff (<code>published_at &lt;= effective_as_of</code>):{" "}
            <strong data-testid="text-viz3d-cutoff-label">{cutoffInfo.label}</strong>
          </span>
          <small>{cutoffInfo.description}</small>
        </label>
        <input
          id="viz3d-cutoff-range"
          data-testid="input-viz3d-cutoff"
          type="range"
          min={0}
          max={2}
          step={1}
          value={cutoffStep}
          onChange={(e) => setCutoffStep(Number(e.target.value) as 0 | 1 | 2)}
        />
      </div>

      <div className="viz3d-node-pills" role="group" aria-label="Inspect provenance node">
        {nodes.map((node) => {
          const palette = nodeColor(node.state);
          return (
            <button
              key={node.id}
              type="button"
              data-testid={`button-viz3d-node-${node.id}`}
              className="viz3d-pill"
              aria-pressed={selectedNode.id === node.id}
              onClick={() => selectNode(node.id)}
            >
              <span
                className="viz3d-dot"
                style={{ backgroundColor: palette.ring }}
                aria-hidden="true"
              />
              {node.label}
            </button>
          );
        })}
      </div>

      <aside
        className="viz3d-inspector"
        data-testid="viz3d-node-inspector"
        aria-label="Selected 3D node provenance details"
      >
        <div>
          <small>{layerTitle(selectedNode.layer)}</small>
          <h4 data-testid="text-viz3d-selected-title">{selectedNode.label}</h4>
          <p>{selectedNode.sublabel}</p>
        </div>
        <dl className="viz3d-meta">
          <div>
            <dt>Status</dt>
            <dd data-testid="text-viz3d-selected-status">{nodeColor(selectedNode.state).badge}</dd>
          </div>
          <div>
            <dt>Published at</dt>
            <dd>
              <code>{selectedNode.publishedAt}</code>
            </dd>
          </div>
          <div>
            <dt>Formula / Hash</dt>
            <dd>
              <code>{selectedNode.formulaOrHash}</code>
            </dd>
          </div>
        </dl>
      </aside>
    </section>
  );
}
