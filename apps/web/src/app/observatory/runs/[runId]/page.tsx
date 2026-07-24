import Link from "next/link";

import { EvidenceFailureState } from "../../../../components/EvidenceFailureState";
import { EventReplay } from "../../../../components/EventReplay";
import { FeedbackControl } from "../../../../components/FeedbackControl";
import { ObservatoryTrace } from "../../../../components/ObservatoryTrace";
import { RerunButton } from "../../../../components/RerunButton";
import { getEvidenceSource } from "../../../../lib/data/server";
import { observatoryFailureState } from "../../../../lib/observatory/errors";
import { sanitizeObservatoryError } from "../../../../lib/observatory/known-errors";
import type { QuerySnapshot } from "../../../../lib/observatory/query-source";
import { buildDocumentIdByVersionId } from "../../../../lib/observatory/reader-links";
import { getObservatorySource } from "../../../../lib/observatory/server";

export const dynamic = "force-dynamic";

export default async function ObservatoryRunPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams?: Promise<{ error?: string; feedback?: string }>;
}) {
  const { runId } = await params;
  const { error, feedback } = (await searchParams) ?? {};
  const safeError = sanitizeObservatoryError(error);
  const source = getObservatorySource();

  let trace;
  try {
    trace = await source.getRun(runId);
  } catch (caught) {
    const kind = observatoryFailureState(caught);
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw caught;
  }

  // Snapshot supplies the question and sibling runs; non-fatal on failure.
  let snapshot: QuerySnapshot | undefined;
  try {
    snapshot = await source.getQuery(trace.query_id);
  } catch {
    snapshot = undefined;
  }

  // Reader deep links are best-effort: an unavailable evidence source disables
  // candidate links rather than failing the whole trace view.
  let documentIdByVersionId: Record<string, string>;
  try {
    documentIdByVersionId = await buildDocumentIdByVersionId(getEvidenceSource());
  } catch {
    documentIdByVersionId = {};
  }

  const compareWith = snapshot?.runs.find((run) => run.run_id !== runId)?.run_id;

  return (
    <main className="page-main">
      <p>
        <Link href="/observatory">← Search Observatory</Link>
      </p>
      <h1>Retrieval run</h1>

      {safeError && (
        <p className="reader-banner citation-error" role="alert">
          Action failed: {safeError}
        </p>
      )}
      {feedback === "recorded" && (
        <p className="reader-banner" role="status">
          Feedback recorded.
        </p>
      )}

      <div className="obs-actions">
        <RerunButton queryId={trace.query_id} runId={runId} />
        {compareWith && (
          <Link className="retry-button" href={`/observatory/compare?a=${runId}&b=${compareWith}`}>
            Compare with run {compareWith.slice(0, 8)}
          </Link>
        )}
      </div>

      <ObservatoryTrace
        trace={trace}
        snapshot={snapshot}
        documentIdByVersionId={documentIdByVersionId}
      />

      <section className="panel-card" aria-labelledby="obs-feedback-heading">
        <h2 id="obs-feedback-heading">Evidence feedback</h2>
        <ul className="obs-feedback-list">
          {trace.candidates.map((candidate) => (
            <li key={candidate.item_id}>
              <span className="obs-muted">
                {candidate.kind} {candidate.item_id.slice(0, 8)}
              </span>
              <FeedbackControl runId={runId} itemId={candidate.item_id} />
            </li>
          ))}
        </ul>
      </section>

      <EventReplay trace={trace} />
    </main>
  );
}
