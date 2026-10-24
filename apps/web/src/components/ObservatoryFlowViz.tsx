import type { RetrievalTrace } from "../lib/observatory/query-source";
import {
  claimViews,
  LANE_LABELS,
  LANES,
  laneColumns,
  partitionCandidates,
  type Lane,
} from "../lib/observatory/trace-view";

function laneColor(lane: Lane): string {
  switch (lane) {
    case "dense":
      return "#388bfd";
    case "lexical":
      return "#a371f7";
    case "facts":
      return "#2ea043";
    case "tables":
      return "#d29922";
    default: {
      const _never: never = lane;
      return _never;
    }
  }
}

/**
 * Interactive / visual 4-Lane RRF Fusion Sankey Flow & Latency/Budget Gauge
 * for the Search Observatory. Uses `laneColumns`, `partitionCandidates` and
 * `claimViews` so future-dated or cross-version evidence is never counted as
 * supported.
 */
export function ObservatoryFlowViz({ trace }: { trace: RetrievalTrace }) {
  const columns = laneColumns(trace);
  const { supported, rejected } = partitionCandidates(trace);
  const claims = claimViews(trace);

  const supportedClaims = claims.filter((c) => c.displayStatus === "supported").length;
  const flaggedClaims = claims.length - supportedClaims;

  const totalCandidates = supported.length + rejected.length;
  const timingEntries = Object.entries(trace.timings_ms);
  const totalLatencyMs = timingEntries.reduce((acc, [, ms]) => acc + ms, 0);

  const contextItemsUsed = trace.budget_usage.context_items;
  const contextItemsCap = Math.max(1, trace.plan.budgets.context_items);
  const contextUtilizationPct = Math.min(
    100,
    Math.round((contextItemsUsed / contextItemsCap) * 100),
  );

  return (
    <section
      className="panel-card obs-flow-card"
      data-testid="observatory-flow-viz"
      aria-labelledby="obs-flow-heading"
    >
      <div className="obs-flow-header">
        <div>
          <h2 id="obs-flow-heading">Pipeline flow &amp; RRF fusion arena</h2>
          <p className="obs-muted" style={{ margin: "0.15rem 0 0" }}>
            4-lane candidate retrieval → Reciprocal Rank Fusion (<code>k=60</code>) → Temporal &amp;
            version gates → Claim entailment
          </p>
        </div>
        <div className="obs-flow-pills">
          <span className="badge badge-ok">{supported.length} supported</span>
          <span className="badge badge-warning">{rejected.length} rejected</span>
          <span className="badge badge-info">{totalLatencyMs} ms total</span>
        </div>
      </div>

      <svg
        viewBox="0 0 860 250"
        className="obs-flow-svg"
        role="img"
        aria-label={`Retrieval pipeline flow: ${totalCandidates} candidates across 4 lanes fused via RRF k=60 into ${supported.length} supported items, ${rejected.length} rejected items, and ${claims.length} claims`}
      >
        {/* Stage Column Headers */}
        <text x="24" y="22" fill="currentColor" fontSize="11" fontWeight="700" opacity="0.75">
          1. RETRIEVAL LANES
        </text>
        <text x="295" y="22" fill="currentColor" fontSize="11" fontWeight="700" opacity="0.75">
          2. RRF FUSION (k=60)
        </text>
        <text x="530" y="22" fill="currentColor" fontSize="11" fontWeight="700" opacity="0.75">
          3. CUTOFF &amp; VERSION GATES
        </text>
        <text x="720" y="22" fill="currentColor" fontSize="11" fontWeight="700" opacity="0.75">
          4. CLAIMS
        </text>

        {/* Left: 4 Retrieval Lanes */}
        {LANES.map((lane, index) => {
          const rows = columns[lane];
          const y = 38 + index * 50;
          const color = laneColor(lane);
          const strokeWidth = Math.max(2, Math.min(12, rows.length * 4));
          return (
            <g key={lane} data-testid={`obs-flow-lane-${lane}`}>
              {/* Curved Sankey ribbon to RRF Nexus */}
              <path
                d={`M 184 ${y + 18} C 235 ${y + 18}, 240 128, 290 128`}
                fill="none"
                stroke={color}
                strokeWidth={strokeWidth}
                strokeOpacity={rows.length > 0 ? 0.65 : 0.2}
                strokeDasharray={rows.length > 0 ? undefined : "4 4"}
              />
              <rect
                x="20"
                y={y}
                width="164"
                height="36"
                rx="7"
                fill={color}
                fillOpacity="0.14"
                stroke={color}
                strokeWidth="1.5"
              />
              <text x="32" y={y + 16} fill="currentColor" fontSize="12" fontWeight="700">
                {LANE_LABELS[lane]}
              </text>
              <text x="32" y={y + 29} fill="currentColor" fontSize="10" opacity="0.8">
                {rows.length} hit{rows.length === 1 ? "" : "s"}
              </text>
            </g>
          );
        })}

        {/* Center-Left: RRF k=60 Fusion Nexus */}
        <g data-testid="obs-flow-rrf-nexus">
          <rect
            x="290"
            y="84"
            width="156"
            height="88"
            rx="10"
            fill="#1f2d4d"
            stroke="#58a6ff"
            strokeWidth="2"
          />
          <text x="368" y="114" textAnchor="middle" fill="#f0f6fc" fontSize="13" fontWeight="700">
            RRF Fusion
          </text>
          <text x="368" y="133" textAnchor="middle" fill="#79c0ff" fontSize="11">
            k = 60 · {totalCandidates} candidates
          </text>
          <text x="368" y="152" textAnchor="middle" fill="#c9d1d9" fontSize="10">
            Deterministic tie-break
          </text>
        </g>

        {/* Flow from RRF Nexus to Supported vs Rejected Gates */}
        <path
          d="M 446 114 C 485 114, 490 78, 530 78"
          fill="none"
          stroke="#2ea043"
          strokeWidth={Math.max(3, supported.length * 4)}
          strokeOpacity="0.75"
        />
        <path
          d="M 446 144 C 485 144, 490 178, 530 178"
          fill="none"
          stroke="#d29922"
          strokeWidth={Math.max(2, rejected.length * 4)}
          strokeOpacity="0.75"
        />

        {/* Center-Right Top: Supported Context Set */}
        <g data-testid="obs-flow-supported-box">
          <rect
            x="530"
            y="48"
            width="148"
            height="62"
            rx="8"
            fill="#162925"
            stroke="#3fb950"
            strokeWidth="1.5"
          />
          <text x="544" y="72" fill="#56d364" fontSize="12" fontWeight="700">
            Supported Set ({supported.length})
          </text>
          <text x="544" y="90" fill="#c9d1d9" fontSize="10">
            Cutoff &amp; version verified
          </text>
        </g>

        {/* Center-Right Bottom: Gate-Rejected Candidates */}
        <g data-testid="obs-flow-rejected-box">
          <rect
            x="530"
            y="146"
            width="148"
            height="62"
            rx="8"
            fill="#2b1d1e"
            stroke="#f78166"
            strokeWidth="1.5"
          />
          <text x="544" y="170" fill="#ffa198" fontSize="12" fontWeight="700">
            Gate Rejected ({rejected.length})
          </text>
          <text x="544" y="188" fill="#c9d1d9" fontSize="10">
            Future / cross-version
          </text>
        </g>

        {/* Flow from Supported to Claims */}
        <path
          d="M 678 78 C 698 78, 700 112, 720 112"
          fill="none"
          stroke="#3fb950"
          strokeWidth={Math.max(3, claims.length * 3.5)}
          strokeOpacity="0.8"
        />

        {/* Right: Claim Decomposition Box */}
        <g data-testid="obs-flow-claims-box">
          <rect
            x="720"
            y="68"
            width="124"
            height="92"
            rx="8"
            fill="#182338"
            stroke="#a371f7"
            strokeWidth="1.5"
          />
          <text x="732" y="92" fill="#d2a8ff" fontSize="12" fontWeight="700">
            Claims ({claims.length})
          </text>
          <text x="732" y="114" fill="#56d364" fontSize="10.5">
            • {supportedClaims} entailed
          </text>
          <text x="732" y="132" fill="#ffa198" fontSize="10.5">
            • {flaggedClaims} flagged
          </text>
          <text x="732" y="148" fill="#8b949e" fontSize="9.5">
            Span-hash checked
          </text>
        </g>
      </svg>

      {/* Visual Context Budget & Stage Latency Bar */}
      <div className="obs-flow-meters">
        <div className="obs-meter-box">
          <div className="obs-meter-label">
            <span>
              <strong>Context budget utilization:</strong> {contextItemsUsed} / {contextItemsCap}{" "}
              items ({trace.budget_usage.context_tokens} tokens)
            </span>
            <span>{contextUtilizationPct}%</span>
          </div>
          <div className="obs-meter-track" aria-hidden="true">
            <div className="obs-meter-fill" style={{ width: `${contextUtilizationPct}%` }} />
          </div>
        </div>

        {timingEntries.length > 0 && (
          <div className="obs-meter-box">
            <div className="obs-meter-label">
              <span>
                <strong>Stage latency distribution:</strong> {totalLatencyMs} ms total
              </span>
              <span>Cost: ${trace.cost_usd}</span>
            </div>
            <div className="obs-Stage-bar" role="list" aria-label="Stage latencies">
              {timingEntries.map(([stage, ms]) => (
                <span key={stage} role="listitem" className="obs-stage-chip">
                  <b>{stage}:</b> {ms} ms
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
