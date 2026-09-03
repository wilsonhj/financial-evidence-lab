"use client";

import { useEffect, useMemo, useState } from "react";
import {
  buildAppliedFacts,
  buildReviewDecision,
  canApplyApprovedFacts,
  canSaveResolution,
  readStoredTheme,
  writeStoredTheme,
  resolveVisibleClaimId,
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

export default function DeskClient() {
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
  const [theme, setTheme] = useState<DeskTheme>("system");
  const [themeReady, setThemeReady] = useState(false);
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
    setTheme(readStoredTheme(document.documentElement.dataset.felTheme ?? null));
    setThemeReady(true);
  }, []);
  useEffect(() => {
    if (!themeReady) return;
    document.documentElement.dataset.felTheme = theme;
    writeStoredTheme(theme);
    document.cookie = `fel-theme=${theme}; Path=/; Max-Age=31536000; SameSite=Lax`;
  }, [theme, themeReady]);
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
    <main className="desk-shell" data-testid="desk-shell">
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
            {section === "coverage" && <Coverage onOpen={() => selectSection("research")} />}
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
              <Model scenario={scenario} setScenario={setScenario} applied={applied} />
            )}
          </section>
          {inspector && <Inspector gatesReady={gatesReady} applied={applied} />}
        </div>
      </section>
    </main>
  );
}

function Coverage({ onOpen }: { onOpen: () => void }) {
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
  const selected = visibleClaims.find((item) => item.id === claim) ?? visibleClaims[0];
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
function Model({
  scenario,
  setScenario,
  applied,
}: {
  scenario: string;
  setScenario: (value: string) => void;
  applied: boolean;
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
function Inspector({ gatesReady, applied }: { gatesReady: boolean; applied: boolean }) {
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
