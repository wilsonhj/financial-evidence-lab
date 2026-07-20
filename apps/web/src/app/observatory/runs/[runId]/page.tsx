import Link from "next/link";

import { EvidenceFailureState } from "../../../../components/EvidenceFailureState";
import { ObservatoryTrace } from "../../../../components/ObservatoryTrace";
import { getEvidenceSource } from "../../../../lib/data/server";
import { observatoryFailureState } from "../../../../lib/observatory/errors";
import type { QuerySnapshot } from "../../../../lib/observatory/query-source";
import { buildDocumentIdByVersionId } from "../../../../lib/observatory/reader-links";
import { getObservatorySource } from "../../../../lib/observatory/server";

export const dynamic = "force-dynamic";

export default async function ObservatoryRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const source = getObservatorySource();

  let trace;
  try {
    trace = await source.getRun(runId);
  } catch (error) {
    const kind = observatoryFailureState(error);
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw error;
  }

  // The snapshot supplies the question and run history; failing to fetch it is
  // non-fatal — the trace still renders without the question header.
  let snapshot: QuerySnapshot | undefined;
  try {
    snapshot = await source.getQuery(trace.query_id);
  } catch {
    snapshot = undefined;
  }

  // Reader deep-links are best-effort: an unavailable evidence source disables
  // candidate links rather than failing the whole trace view.
  let documentIdByVersionId: Record<string, string>;
  try {
    documentIdByVersionId = await buildDocumentIdByVersionId(getEvidenceSource());
  } catch {
    documentIdByVersionId = {};
  }

  return (
    <main className="page-main">
      <p>
        <Link href="/observatory">← Search Observatory</Link>
      </p>
      <h1>Retrieval run</h1>
      <ObservatoryTrace
        trace={trace}
        snapshot={snapshot}
        documentIdByVersionId={documentIdByVersionId}
      />
    </main>
  );
}
