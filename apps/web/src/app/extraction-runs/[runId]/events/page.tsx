import { getExtractionSource } from "../../../../lib/extraction/source";
import { guards } from "../../../../lib/extraction/contracts";
import { pageQuery } from "../../../../lib/extraction/page-query";
import {
  ExtractionShell,
  ExtractionError,
  ExtractionPagination,
} from "../../../../components/extraction/display";
export const dynamic = "force-dynamic";
export default async function EventHistoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  try {
    const source = getExtractionSource(),
      { runId } = await params,
      query = pageQuery(await searchParams);
    const { data: page } = await source.read(`runs/${runId}/event-history`, guards.events, query);
    return (
      <ExtractionShell title="Stored extraction events" mode={source.mode}>
        <p>Run {runId}. This bounded page is stored history.</p>
        {!page.items.length ? (
          <p>No events on this page.</p>
        ) : (
          <table>
            <caption>Persisted events in order</caption>
            <thead>
              <tr>
                <th>ID</th>
                <th>Type</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((e) => (
                <tr key={e.id}>
                  <td>{e.id}</td>
                  <td>{e.type}</td>
                  <td>{e.occurred_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <ExtractionPagination
          path={`/extraction-runs/${runId}/events`}
          query={Object.fromEntries(query)}
          page={page}
        />
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Stored extraction events">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}
