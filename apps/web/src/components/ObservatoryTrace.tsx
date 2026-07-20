import Link from "next/link";

import type {
  Candidate,
  QuerySnapshot,
  RetrievalCitation,
  RetrievalTrace,
} from "../lib/observatory/query-source";
import {
  claimViews,
  decisionTimeline,
  describeRunState,
  laneColumns,
  LANES,
  partitionCandidates,
  readerHref,
  type ClaimDisplayStatus,
  type Lane,
} from "../lib/observatory/trace-view";

const LANE_LABELS: Record<Lane, string> = {
  dense: "Dense",
  lexical: "Lexical",
  facts: "Facts",
  tables: "Tables",
};

function claimBadgeClass(status: ClaimDisplayStatus): string {
  if (status === "supported") return "badge badge-ok";
  if (status === "contradicted" || status === "unverifiable") return "badge badge-warning";
  return "badge badge-info";
}

function citationBadgeClass(status: RetrievalCitation["status"]): string {
  if (status === "entailed") return "badge badge-ok";
  if (status === "contradictory" || status === "irrelevant") return "badge badge-warning";
  return "badge badge-info";
}

function CandidateRef({
  candidate,
  documentIdByVersionId,
}: {
  candidate: Candidate;
  documentIdByVersionId: Readonly<Record<string, string>>;
}) {
  const href = readerHref(candidate, documentIdByVersionId);
  const label = `${candidate.kind} ${candidate.item_id.slice(0, 8)}`;
  if (!href) {
    return (
      <span className="candidate-ref" title="Reader link unavailable for this version">
        {label}
      </span>
    );
  }
  return (
    <Link className="candidate-ref" href={href}>
      Open evidence <span className="visually-hidden">for {label} in the reader</span>
    </Link>
  );
}

function PlanSection({ snapshot, trace }: { snapshot?: QuerySnapshot; trace: RetrievalTrace }) {
  const { plan } = trace;
  return (
    <section className="panel-card" aria-labelledby="obs-plan-heading">
      <h2 id="obs-plan-heading">Query plan</h2>
      {snapshot && <p className="obs-question">{snapshot.question}</p>}
      <dl className="obs-meta">
        <div>
          <dt>Intent</dt>
          <dd>{plan.intent}</dd>
        </div>
        <div>
          <dt>Effective cutoff</dt>
          <dd>{plan.effective_as_of}</dd>
        </div>
        <div>
          <dt>Corpus version</dt>
          <dd>{plan.corpus_version_id}</dd>
        </div>
        <div>
          <dt>Index version</dt>
          <dd>{plan.index_version_id}</dd>
        </div>
        <div>
          <dt>Lanes</dt>
          <dd>{plan.lanes.join(", ")}</dd>
        </div>
        <div>
          <dt>Filters</dt>
          <dd>
            {[
              plan.filters.forms?.length ? `forms: ${plan.filters.forms.join(", ")}` : null,
              plan.filters.periods?.length ? `periods: ${plan.filters.periods.join(", ")}` : null,
            ]
              .filter(Boolean)
              .join("; ") || "none"}
          </dd>
        </div>
      </dl>
      {plan.variants.length > 0 && (
        <>
          <h3>Query variants</h3>
          <ul className="obs-variants">
            {plan.variants.map((variant, index) => (
              <li key={index}>{variant}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function BudgetSection({ trace }: { trace: RetrievalTrace }) {
  const { budgets } = trace.plan;
  const usage = trace.budget_usage;
  return (
    <section className="panel-card" aria-labelledby="obs-budget-heading">
      <h2 id="obs-budget-heading">Budgets, latency and cost</h2>
      <table className="doc-table">
        <caption className="visually-hidden">Budget limits, usage, latency and cost</caption>
        <tbody>
          <tr>
            <th scope="row">Context items</th>
            <td>
              {usage.context_items} / {budgets.context_items}
            </td>
          </tr>
          <tr>
            <th scope="row">Context tokens</th>
            <td>{usage.context_tokens}</td>
          </tr>
          <tr>
            <th scope="row">Input / output tokens</th>
            <td>
              {usage.input_tokens} / {usage.output_tokens}
            </td>
          </tr>
          <tr>
            <th scope="row">Cost (USD)</th>
            <td>{trace.cost_usd}</td>
          </tr>
          {Object.entries(trace.timings_ms).map(([stage, ms]) => (
            <tr key={stage}>
              <th scope="row">Latency: {stage}</th>
              <td>{ms} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function LaneSection({
  trace,
  documentIdByVersionId,
}: {
  trace: RetrievalTrace;
  documentIdByVersionId: Readonly<Record<string, string>>;
}) {
  const columns = laneColumns(trace);
  return (
    <section className="panel-card" aria-labelledby="obs-lanes-heading">
      <h2 id="obs-lanes-heading">Retrieval lanes</h2>
      <div className="obs-lane-grid">
        {LANES.map((lane) => (
          <div key={lane} className="obs-lane">
            <h3>{LANE_LABELS[lane]}</h3>
            {columns[lane].length === 0 ? (
              <p className="obs-empty">No candidates in this lane.</p>
            ) : (
              <table className="doc-table">
                <caption className="visually-hidden">{LANE_LABELS[lane]} lane candidates</caption>
                <thead>
                  <tr>
                    <th scope="col">Lane #</th>
                    <th scope="col">Raw</th>
                    <th scope="col">Norm</th>
                    <th scope="col">RRF</th>
                    <th scope="col">Fused (rank / score)</th>
                    <th scope="col">Rerank (rank / score)</th>
                    <th scope="col">Status</th>
                    <th scope="col">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {columns[lane].map((row) => (
                    <tr key={`${row.candidate.item_id}-${row.contribution.variant_index}`}>
                      <td>{row.contribution.lane_rank}</td>
                      <td>{row.contribution.raw_score}</td>
                      <td>{row.contribution.normalized_score ?? "—"}</td>
                      <td>{row.contribution.rrf_contribution}</td>
                      <td>
                        {row.fusedRank ?? "—"} / {row.fusedScore}
                      </td>
                      <td>
                        {row.rerankRank ?? "—"} / {row.rerankScore ?? "—"}
                      </td>
                      <td>
                        <span className={row.supported ? "badge badge-ok" : "badge badge-warning"}>
                          {row.supported ? "supported" : "rejected"}
                        </span>
                      </td>
                      <td>
                        <CandidateRef
                          candidate={row.candidate}
                          documentIdByVersionId={documentIdByVersionId}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function TimelineSection({ trace }: { trace: RetrievalTrace }) {
  const entries = decisionTimeline(trace);
  const { rejected } = partitionCandidates(trace);
  return (
    <section className="panel-card" aria-labelledby="obs-timeline-heading">
      <h2 id="obs-timeline-heading">Filter and rejection timeline</h2>
      {entries.length === 0 ? (
        <p className="obs-empty">No decisions recorded.</p>
      ) : (
        <ol className="obs-timeline">
          {entries.map((entry, index) => (
            <li key={index}>
              <span className="badge badge-info">{entry.stage}</span> <code>{entry.code}</code>{" "}
              <span className="obs-muted">
                {entry.itemIds.length} item{entry.itemIds.length === 1 ? "" : "s"} ·{" "}
                {entry.occurredAt}
              </span>
            </li>
          ))}
        </ol>
      )}
      <h3>Rejected candidates</h3>
      {rejected.length === 0 ? (
        <p className="obs-empty">No rejected candidates.</p>
      ) : (
        <ul className="obs-rejected">
          {rejected.map(({ candidate, code }) => (
            <li key={candidate.item_id}>
              <code>{code}</code> — {candidate.kind} {candidate.item_id.slice(0, 8)}{" "}
              <span className="obs-muted">published {candidate.published_at}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ClaimsSection({
  trace,
  documentIdByVersionId,
}: {
  trace: RetrievalTrace;
  documentIdByVersionId: Readonly<Record<string, string>>;
}) {
  const views = claimViews(trace);
  const byItemId = new Map(trace.candidates.map((candidate) => [candidate.item_id, candidate]));
  return (
    <section className="panel-card" aria-labelledby="obs-claims-heading">
      <h2 id="obs-claims-heading">Claims and citations</h2>
      {views.length === 0 ? (
        <p className="obs-empty">No claims generated.</p>
      ) : (
        <ul className="obs-claims">
          {views.map(({ claim, displayStatus, downgraded }) => (
            <li key={claim.id} className="obs-claim">
              <p className="obs-claim-text">
                <span className={claimBadgeClass(displayStatus)}>{displayStatus}</span> {claim.text}
              </p>
              {downgraded && (
                <p className="obs-muted" role="note">
                  Downgraded: cites evidence outside the supported set.
                </p>
              )}
              <ul className="obs-citations">
                {claim.citations.map((citation, index) => {
                  const candidate = byItemId.get(citation.item_id);
                  return (
                    <li key={index}>
                      <span className={citationBadgeClass(citation.status)}>{citation.status}</span>{" "}
                      {candidate ? (
                        <CandidateRef
                          candidate={candidate}
                          documentIdByVersionId={documentIdByVersionId}
                        />
                      ) : (
                        <span className="obs-muted">item {citation.item_id.slice(0, 8)}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Presentational Observatory trace view. Pure and server-renderable: every
 * "supported" affordance is gated by the trace-view integrity guard, so
 * future, cross-version or rejected evidence can never render as supported.
 */
export function ObservatoryTrace({
  trace,
  snapshot,
  documentIdByVersionId,
}: {
  trace: RetrievalTrace;
  snapshot?: QuerySnapshot;
  documentIdByVersionId: Readonly<Record<string, string>>;
}) {
  const runState = describeRunState(trace.status);
  return (
    <div className="obs-trace">
      <p className="obs-status">
        Run status: <span className="badge badge-info">{trace.status}</span>
      </p>
      {runState && (
        <section
          className={`reader-banner ${runState.tone === "warning" ? "citation-error" : ""}`}
          role={runState.tone === "warning" ? "alert" : "status"}
          aria-labelledby="obs-runstate-heading"
        >
          <h2 id="obs-runstate-heading">{runState.heading}</h2>
          <p>{runState.description}</p>
        </section>
      )}
      <PlanSection snapshot={snapshot} trace={trace} />
      <LaneSection trace={trace} documentIdByVersionId={documentIdByVersionId} />
      <TimelineSection trace={trace} />
      <ClaimsSection trace={trace} documentIdByVersionId={documentIdByVersionId} />
      <BudgetSection trace={trace} />
    </div>
  );
}
