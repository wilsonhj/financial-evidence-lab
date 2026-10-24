"use client";

import { useEffect, useMemo, useState } from "react";
import { EvidenceGraph3D } from "../../components/EvidenceGraph3D";
import {
  buildAppliedFacts,
  buildReviewDecision,
  canApplyApprovedFacts,
  canSaveResolution,
  resolveVisibleClaimId,
  writeStoredTheme,
  type AppliedFacts,
  type DeskTheme,
  type EvidenceSourceId,
  type GuidanceApproval,
  type ReviewDecision,
} from "./desk-state";

type Section = "coverage" | "research" | "review" | "model";
type ClaimId = "nrr" | "guidance" | "actuals";

const sections: { id: Section; label: string }[] = [
  { id: "coverage", label: "Coverage" },
  { id: "research", label: "Research" },
  { id: "review", label: "Review" },
  { id: "model", label: "Model" },
];
const claims = [
  {
    id: "nrr",
    title: "NRR differs by source",
    detail: "10-Q 108% versus earnings call 109%",
    status: "Conflict",
  },
  {
    id: "guidance",
    title: "Revenue guidance narrowed",
    detail: "$790–794m revenue · 76.0–76.5% GM",
    status: "2 approvals",
  },
  {
    id: "actuals",
    title: "Reported quarter",
    detail: "$198.4m revenue · $782m ARR · 76.4% GM",
    status: "Reported",
  },
] satisfies { id: ClaimId; title: string; detail: string; status: string }[];
const themeLabels: Record<DeskTheme, string> = {
  system: "System",
  light: "Light",
  oled: "OLED Black",
};

export default function DeskClient({ initialTheme }: { initialTheme: DeskTheme }) {
  const [section, setSection] = useState<Section>("coverage");
  const [claim, setClaim] = useState<ClaimId | null>("nrr");
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<EvidenceSourceId | null>(null);
  const [rationale, setRationale] = useState("");
  const [decision, setDecision] = useState<ReviewDecision | null>(null);
  const [approvals, setApprovals] = useState<GuidanceApproval[]>([
    { claimId: "C-109-revenue", approved: false },
    { claimId: "C-109-gross-margin", approved: false },
  ]);
  const [scenario, setScenario] = useState("Base");
  const [inspector, setInspector] = useState(true);
  const [theme, setTheme] = useState<DeskTheme>(initialTheme);
  const [appliedFacts, setAppliedFacts] = useState<AppliedFacts | null>(null);
  const [themeOpen, setThemeOpen] = useState(false);
  const gatesReady = canApplyApprovedFacts(decision, approvals);
  const applied = appliedFacts !== null;
  const visibleClaims = useMemo(
    () =>
      claims.filter((item) =>
        `${item.title} ${item.detail}`.toLowerCase().includes(search.toLowerCase()),
      ),
    [search],
  );

  useEffect(() => {
    writeStoredTheme(theme);
    document.cookie = `fel-theme=${theme}; Path=/; Max-Age=31536000; SameSite=Lax`;
  }, [theme]);
  useEffect(() => {
    setClaim((current) =>
      resolveVisibleClaimId(
        current,
        visibleClaims.map((visibleClaim) => visibleClaim.id),
      ),
    );
  }, [visibleClaims]);

  const selectSection = (next: Section) => {
    setSection(next);
  };
  return (
    <main className="desk-shell" data-testid="desk-shell" data-fel-theme={theme}>
      <aside className="desk-sidebar" aria-label="Desk sections">
        <div className="desk-brand">
          <span className="brand-dot" />
          Evidence Lab<small>Update desk</small>
        </div>
        <nav>
          {sections.map((item) => (
            <button
              key={item.id}
              data-testid={`nav-section-${item.id}`}
              className={section === item.id ? "active" : ""}
              onClick={() => selectSection(item.id)}
              aria-current={section === item.id ? "page" : undefined}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="desk-user">
          <b>AR</b>
          <span>
            Alex Rivera<small>Coverage analyst</small>
          </span>
        </div>
      </aside>
      <section className="desk-workspace">
        <header className="desk-toolbar">
          <div>
            <p className="eyebrow">CloudMetric · Q2 FY26</p>
            <h2>{sections.find((item) => item.id === section)?.label}</h2>
            <p className="desk-mode-note" data-testid="text-desk-mode">
              Deterministic fixture · review changes stay in this session
            </p>
          </div>
          <label className="desk-search">
            <span className="visually-hidden">Search claims</span>
            <input
              data-testid="input-search-claims"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search evidence"
            />
          </label>
          <button
            data-testid="button-toggle-inspector"
            className="icon-button"
            onClick={() => setInspector(!inspector)}
            aria-pressed={inspector}
            aria-label="Toggle evidence inspector"
          >
            i
          </button>
          <button
            data-testid="button-theme-menu"
            className="icon-button"
            onClick={() => setThemeOpen(!themeOpen)}
            aria-expanded={themeOpen}
            aria-label="Choose appearance"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M20 15.4A8.5 8.5 0 0 1 8.6 4 8.5 8.5 0 1 0 20 15.4Z" />
            </svg>
          </button>
          {themeOpen && (
            <div className="theme-popover" data-testid="theme-popover">
              <b>Appearance</b>
              {(["system", "light", "oled"] as DeskTheme[]).map((value) => (
                <button
                  data-testid={`button-theme-${value}`}
                  key={value}
                  onClick={() => {
                    setTheme(value);
                    setThemeOpen(false);
                  }}
                  aria-pressed={theme === value}
                >
                  {themeLabels[value]}
                  {theme === value && <span>Active</span>}
                </button>
              ))}
            </div>
          )}
        </header>
        <div className={`desk-grid ${inspector ? "" : "inspector-hidden"}`}>
          <section className="desk-content">
            {section === "coverage" && (
              <Coverage
                onOpen={() => selectSection("research")}
                scenario={scenario}
                source={source}
                decision={decision}
                approvals={approvals}
                applied={applied}
              />
            )}
            {section === "research" && (
              <Research
                visibleClaims={visibleClaims}
                claim={claim}
                setClaim={setClaim}
                onReview={() => selectSection("review")}
              />
            )}
            {section === "review" && (
              <Review
                source={source}
                setSource={setSource}
                rationale={rationale}
                setRationale={setRationale}
                decision={decision}
                setDecision={setDecision}
                approvals={approvals}
                setApprovals={setApprovals}
                gatesReady={gatesReady}
                appliedFacts={appliedFacts}
                setAppliedFacts={setAppliedFacts}
              />
            )}
            {section === "model" && (
              <Model
                scenario={scenario}
                setScenario={setScenario}
                applied={applied}
                source={source}
                decision={decision}
                approvals={approvals}
              />
            )}
          </section>
          {inspector && (
            <Inspector
              gatesReady={gatesReady}
              applied={applied}
              decision={decision}
              approvals={approvals}
            />
          )}
        </div>
      </section>
    </main>
  );
}

function Coverage({
  onOpen,
  scenario,
  source,
  decision,
  approvals,
  applied,
}: {
  onOpen: () => void;
  scenario: string;
  source: EvidenceSourceId | null;
  decision: ReviewDecision | null;
  approvals: GuidanceApproval[];
  applied: boolean;
}) {
  return (
    <>
      <p className="desk-intro">Earnings events, filing freshness, and update deadlines.</p>
      <div className="metric-row">
        <Metric label="Events this week" value="12" note="4 need action" />
        <Metric label="Review due" value="3" note="1 overdue" />
        <Metric label="Evidence coverage" value="7 / 9" note="model cells linked" />
      </div>
      <h3>Event inbox</h3>
      <button
        className="event-row selected-event"
        data-testid="button-event-cloudmetric"
        onClick={onOpen}
      >
        <span className="company-mark">CM</span>
        <span>
          <b>CloudMetric Inc.</b>
          <small>10-Q filed · Q2 FY26 · ingested 8m ago</small>
          <strong>$198.4m revenue · $782m ARR · 76.4% GM</strong>
        </span>
        <em>
          1 conflict
          <br />
          Due today · 4:00 PM
        </em>
        <i>Open update</i>
      </button>
      <div className="event-row muted-event">
        <span className="company-mark">NS</span>
        <span>
          <b>Northstar Systems</b>
          <small>8-K earnings release · Q3 FY26</small>
        </span>
        <em>Current</em>
      </div>
      <EvidenceGraph3D
        scenario={scenario}
        source={source}
        decision={decision}
        approvals={approvals}
        applied={applied}
      />
    </>
  );
}

function Research({
  visibleClaims,
  claim,
  setClaim,
  onReview,
}: {
  visibleClaims: typeof claims;
  claim: ClaimId | null;
  setClaim: (id: ClaimId) => void;
  onReview: () => void;
}) {
  const selected = visibleClaims.find((item) => item.id === claim);
  return (
    <div className="research-layout">
      <section className="claim-list">
        <h3>What changed</h3>
        {visibleClaims.length > 0 ? (
          visibleClaims.map((item) => (
            <button
              data-testid={`button-claim-${item.id}`}
              onClick={() => setClaim(item.id)}
              className={claim === item.id ? "claim active-claim" : "claim"}
              aria-pressed={claim === item.id}
              key={item.id}
            >
              <small>{item.status}</small>
              <b>{item.title}</b>
              <span>{item.detail}</span>
            </button>
          ))
        ) : (
          <p className="claim-empty" data-testid="text-empty-claims" role="status">
            No evidence claims match this search.
          </p>
        )}
        <button data-testid="button-open-review" className="primary" onClick={onReview}>
          Send to extraction review
        </button>
      </section>
      {selected ? (
        <EvidenceDetail claimId={selected.id} title={selected.title} />
      ) : (
        <article className="evidence-paper evidence-empty" data-testid="evidence-empty">
          <p className="eyebrow">Exact source evidence</p>
          <h3>No claim selected</h3>
          <p>Clear the search to return to the evidence-backed claim list.</p>
        </article>
      )}
    </div>
  );
}

function EvidenceDetail({ claimId, title }: { claimId: ClaimId; title: string }) {
  return (
    <article className="evidence-paper" data-testid={`evidence-claim-${claimId}`}>
      <p className="eyebrow">
        {claimId === "guidance"
          ? "Exact source evidence · page 42"
          : claimId === "actuals"
            ? "Exact source evidence · page 12"
            : "Exact source evidence · page 34 and call turn 48"}
      </p>
      <h3>{title}</h3>
      {claimId === "nrr" && (
        <>
          <p className="filing-evidence">
            “Dollar-based net retention was <b>108%</b> at July 31, 2026.”
          </p>
          <p className="call-evidence">
            Earnings call: “Net retention ended the quarter at <b>109%</b>.”
          </p>
          <div className="conflict-box" data-testid="status-nrr-conflict" role="alert">
            Conflict: 10-Q 108% versus earnings call 109%. Human resolution required.
          </div>
        </>
      )}
      {claimId === "guidance" && (
        <>
          <p>
            Management expects full-year revenue of <mark>$790–794m</mark>, narrowing the prior
            range.
          </p>
          <p className="filing-evidence">
            “Full-year non-GAAP gross margin is expected to be <b>76.0–76.5%</b>.”
          </p>
        </>
      )}
      {claimId === "actuals" && (
        <>
          <p>
            Revenue was <mark>$198.4m</mark>, an increase of 22% year over year. ARR reached{" "}
            <mark>$782m</mark>.
          </p>
          <p className="filing-evidence">
            “Q2 gross margin was <b>76.4%</b>, up 90 basis points year over year.”
          </p>
        </>
      )}
    </article>
  );
}

function Review(props: {
  source: EvidenceSourceId | null;
  setSource: (value: EvidenceSourceId) => void;
  rationale: string;
  setRationale: (value: string) => void;
  decision: ReviewDecision | null;
  setDecision: (value: ReviewDecision | null) => void;
  approvals: GuidanceApproval[];
  setApprovals: (value: GuidanceApproval[]) => void;
  gatesReady: boolean;
  appliedFacts: AppliedFacts | null;
  setAppliedFacts: (value: AppliedFacts | null) => void;
}) {
  const chooseSource = (source: EvidenceSourceId) => {
    props.setSource(source);
    props.setDecision(null);
    props.setAppliedFacts(null);
  };
  const updateRationale = (rationale: string) => {
    props.setRationale(rationale);
    props.setDecision(null);
    props.setAppliedFacts(null);
  };
  const toggle = (index: number) => {
    props.setApprovals(
      props.approvals.map((approval, i) =>
        i === index ? { ...approval, approved: !approval.approved } : approval,
      ),
    );
    props.setAppliedFacts(null);
  };
  return (
    <div className="review-layout">
      <section className="review-card">
        <p className="eyebrow">C-104 · source conflict</p>
        <h3>Choose the authoritative NRR source</h3>
        <div className="source-options">
          <button
            data-testid="button-source-filing"
            onClick={() => chooseSource("sec-10q-nrr")}
            aria-pressed={props.source === "sec-10q-nrr"}
          >
            <b>10-Q · 108%</b>
            <span>Evidence ID sec-10q-nrr</span>
          </button>
          <button
            data-testid="button-source-call"
            onClick={() => chooseSource("call-turn-48")}
            aria-pressed={props.source === "call-turn-48"}
          >
            <b>Earnings call · 109%</b>
            <span>Evidence ID call-turn-48</span>
          </button>
        </div>
        <label>
          Resolution rationale
          <textarea
            data-testid="input-rationale"
            value={props.rationale}
            onChange={(event) => updateRationale(event.target.value)}
            placeholder="Explain why this source governs the model…"
          />
        </label>
        <button
          data-testid="button-save-resolution"
          className="primary"
          disabled={!canSaveResolution(props.source, props.rationale)}
          onClick={() => props.setDecision(buildReviewDecision(props.source, props.rationale))}
        >
          {props.decision ? "Resolution saved for session" : "Save session resolution"}
        </button>
      </section>
      <section className="review-card">
        <p className="eyebrow">C-109 · guidance validation</p>
        <h3>Two approvals required</h3>
        <p>
          <b>$790–794m</b> revenue guidance · <b>76.0–76.5%</b> GM guidance
        </p>
        {props.approvals.map((approval, index) => (
          <label className="approval" key={approval.claimId}>
            <input
              data-testid={`checkbox-approval-${index + 1}`}
              type="checkbox"
              checked={approval.approved}
              onChange={() => toggle(index)}
            />
            {approval.claimId === "C-109-revenue"
              ? "Revenue guidance range verified"
              : "Gross margin range verified"}
            <span>{approval.approved ? "Approved" : "Pending"}</span>
          </label>
        ))}
        <button
          data-testid="button-apply-facts"
          className="primary"
          disabled={!props.gatesReady}
          onClick={() => props.setAppliedFacts(buildAppliedFacts(props.decision, props.approvals))}
        >
          {props.appliedFacts ? "Facts staged in model preview" : "Apply approved facts"}
        </button>
        <small className="gate-note" data-testid="status-review-gates" aria-live="polite">
          {props.gatesReady
            ? "All review gates complete."
            : "Choose a source, save the resolution, and complete both guidance approvals."}
        </small>
      </section>
    </div>
  );
}

function ScenarioWaterfallChart({
  scenario,
  decision,
}: {
  scenario: string;
  decision: ReviewDecision | null;
}) {
  const nrrLabel = decision?.sourceId === "call-turn-48" ? "+$70.4m (109%)" : "+$62.6m (108%)";
  const scenarioDelta: Record<
    string,
    { delta: string; total: string; barHeight: number; color: string }
  > = {
    Base: { delta: "+$0.0m (Base)", total: "$842.4m", barHeight: 132, color: "#388bfd" },
    Bull: { delta: "+$14.7m (Bull)", total: "$857.1m", barHeight: 148, color: "#2ea043" },
    Bear: { delta: "-$18.6m (Bear)", total: "$823.8m", barHeight: 112, color: "#d29922" },
  };
  const active = scenarioDelta[scenario] ?? scenarioDelta.Base!;

  return (
    <section
      className="waterfall-card"
      data-testid="scenario-waterfall-chart"
      aria-label="FY27 Revenue Bridge and Scenario Sensitivity Chart"
    >
      <div className="waterfall-header">
        <div>
          <p className="eyebrow">Deterministic Decimal Bridge · FY26 → FY27</p>
          <h3>Scenario Waterfall &amp; Guidance Corridor</h3>
        </div>
        <span className="waterfall-badge">{scenario} Scenario Active</span>
      </div>
      <svg
        viewBox="0 0 640 210"
        className="waterfall-svg"
        role="img"
        aria-label={`Waterfall chart showing Q2 ARR $782.0m building to ${active.total} under ${scenario} scenario`}
      >
        {/* Background grid lines */}
        <line x1="40" y1="30" x2="610" y2="30" stroke="currentColor" strokeOpacity="0.12" />
        <line x1="40" y1="80" x2="610" y2="80" stroke="currentColor" strokeOpacity="0.12" />
        <line x1="40" y1="130" x2="610" y2="130" stroke="currentColor" strokeOpacity="0.12" />
        <line x1="40" y1="170" x2="610" y2="170" stroke="currentColor" strokeOpacity="0.24" />

        {/* Bar 1: Q2 ARR Base */}
        <g>
          <rect x="64" y="62" width="96" height="108" rx="6" fill="#388bfd" fillOpacity="0.85" />
          <text
            x="112"
            y="54"
            textAnchor="middle"
            fill="currentColor"
            fontSize="11"
            fontWeight="700"
          >
            $782.0m
          </text>
          <text x="112" y="188" textAnchor="middle" fill="currentColor" fontSize="10.5">
            Q2 ARR Base
          </text>
        </g>

        {/* Connector 1 -> 2 */}
        <line
          x1="160"
          y1="62"
          x2="196"
          y2="62"
          stroke="currentColor"
          strokeDasharray="3 3"
          strokeOpacity="0.4"
        />

        {/* Bar 2: NRR Expansion */}
        <g>
          <rect x="196" y="38" width="96" height="24" rx="5" fill="#2ea043" />
          <text
            x="244"
            y="30"
            textAnchor="middle"
            fill="currentColor"
            fontSize="10.5"
            fontWeight="700"
          >
            {nrrLabel}
          </text>
          <text x="244" y="188" textAnchor="middle" fill="currentColor" fontSize="10.5">
            Net Retention
          </text>
        </g>

        {/* Connector 2 -> 3 */}
        <line
          x1="292"
          y1="38"
          x2="328"
          y2="38"
          stroke="currentColor"
          strokeDasharray="3 3"
          strokeOpacity="0.4"
        />

        {/* Bar 3: Scenario Override */}
        <g>
          <rect
            x="328"
            y={scenario === "Bear" ? 38 : 26}
            width="96"
            height={scenario === "Base" ? 8 : 16}
            rx="4"
            fill={active.color}
          />
          <text
            x="376"
            y="19"
            textAnchor="middle"
            fill="currentColor"
            fontSize="10.5"
            fontWeight="700"
          >
            {active.delta}
          </text>
          <text x="376" y="188" textAnchor="middle" fill="currentColor" fontSize="10.5">
            Scenario Override
          </text>
        </g>

        {/* Connector 3 -> 4 */}
        <line
          x1="424"
          y1="38"
          x2="468"
          y2="38"
          stroke="currentColor"
          strokeDasharray="3 3"
          strokeOpacity="0.4"
        />

        {/* Bar 4: FY27 Revenue Output */}
        <g>
          <rect
            x="468"
            y={170 - active.barHeight}
            width="112"
            height={active.barHeight}
            rx="6"
            fill={active.color}
          />
          <text
            x="524"
            y={162 - active.barHeight}
            textAnchor="middle"
            fill="currentColor"
            fontSize="12"
            fontWeight="700"
          >
            {active.total}
          </text>
          <text
            x="524"
            y="188"
            textAnchor="middle"
            fill="currentColor"
            fontSize="10.5"
            fontWeight="600"
          >
            FY27 Revenue
          </text>
        </g>
      </svg>
    </section>
  );
}

function Model({
  scenario,
  setScenario,
  applied,
  source,
  decision,
  approvals,
}: {
  scenario: string;
  setScenario: (value: string) => void;
  applied: boolean;
  source: EvidenceSourceId | null;
  decision: ReviewDecision | null;
  approvals: GuidanceApproval[];
}) {
  const values: Record<string, string> = { Base: "$842.4m", Bull: "$857.1m", Bear: "$823.8m" };
  return (
    <>
      <div className="scenario-tabs" role="group" aria-label="Model scenario">
        {["Base", "Bull", "Bear"].map((item) => (
          <button
            data-testid={`button-scenario-${item.toLowerCase()}`}
            onClick={() => setScenario(item)}
            aria-pressed={scenario === item}
            key={item}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="model-card">
        <p className="eyebrow">FY27 revenue · {scenario} case</p>
        <strong data-testid="text-fy27-revenue">{values[scenario]}</strong>
        <span data-testid="text-fy27-caption">
          {applied
            ? "Facts staged in this session · preview figures unchanged"
            : "Awaiting approved facts"}
        </span>
      </div>
      <ScenarioWaterfallChart scenario={scenario} decision={decision} />
      <EvidenceGraph3D
        scenario={scenario}
        source={source}
        decision={decision}
        approvals={approvals}
        applied={applied}
      />
      <div className="packet-card">
        <h3>PM packet</h3>
        <p data-testid="text-packet-readiness">
          {applied
            ? "Session gates complete · packet export is not available"
            : "Not ready · 3 review gates remain"}
        </p>
        <button data-testid="button-packet-readiness" disabled>
          {applied ? "Packet export not available" : "Complete review gates"}
        </button>
      </div>
    </>
  );
}

function Inspector({
  gatesReady,
  applied,
  decision,
  approvals,
}: {
  gatesReady: boolean;
  applied: boolean;
  decision: ReviewDecision | null;
  approvals: GuidanceApproval[];
}) {
  const completedCount =
    (decision !== null ? 1 : 0) + approvals.filter((item) => item.approved).length;
  return (
    <aside className="inspector" data-testid="evidence-inspector">
      <h3>Impact Inspector</h3>
      <p>Model v19 · evidence-linked</p>
      <div className="inspector-metric">
        <small>FY27 revenue (fixture preview)</small>
        <b>$842.4m</b>
        <span>Static fixture copy · not a computed impact</span>
      </div>
      <h4>Evidence coverage</h4>
      <div className="coverage-bar">
        <i />
      </div>
      <b>7 / 9 cells linked</b>
      <div className="inspector-gates">
        <b>{applied ? "Applied" : gatesReady ? "Ready to apply" : "3 review gates"}</b>
        <span>
          {gatesReady
            ? "Rationale and approvals captured"
            : "Resolve NRR conflict and approve guidance"}
        </span>
        <small className="gate-note">Gate progress: {completedCount} / 3 verified</small>
      </div>
    </aside>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="metric-card">
      <small>{label}</small>
      <b>{value}</b>
      <span>{note}</span>
    </div>
  );
}
