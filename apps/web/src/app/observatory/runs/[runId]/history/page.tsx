import Link from "next/link";
import { EvidenceFailureState } from "../../../../../components/EvidenceFailureState";
import { PageNavigation } from "../../../../../components/PageNavigation";
import { getObservatorySource } from "../../../../../lib/observatory/server";
import { observatoryFailureState } from "../../../../../lib/observatory/errors";

export const dynamic = "force-dynamic";

export default async function EventHistoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams?: Promise<{ cursor?: string; order?: "asc" | "desc" }>;
}) {
  const { runId } = await params;
  const search = (await searchParams) ?? {};
  let page;
  try {
    page = await getObservatorySource().getEventHistory(runId, {
      limit: 50,
      cursor: search.cursor,
      order: search.order ?? "asc",
    });
  } catch (caught) {
    const kind = observatoryFailureState(caught);
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw caught;
  }
  return (
    <main id="main-content" tabIndex={-1} className="page-main">
      <Link href={`/observatory/runs/${encodeURIComponent(runId)}`}>Back to retrieval run</Link>
      <h1>Persisted event history</h1>
      <p>Showing one page of recorded events.</p>
      <PageNavigation
        path={`/observatory/runs/${encodeURIComponent(runId)}/history`}
        nextCursor={page.next_cursor}
        previousCursor={page.previous_cursor}
        order={search.order ?? "asc"}
        label="Event history pages"
      />
      <ol className="obs-replay">
        {page.items.map((event) => (
          <li key={event.seq}>
            <span className="badge badge-info">#{event.seq}</span> <code>{event.type}</code>{" "}
            <span className="obs-muted">{event.occurred_at}</span>
          </li>
        ))}
      </ol>
    </main>
  );
}
