import Link from "next/link";
import { getExtractionSource } from "../../lib/extraction/source";
import { guards } from "../../lib/extraction/contracts";
import { pageQuery } from "../../lib/extraction/page-query";
import {
  ExtractionShell,
  ExtractionError,
  ExtractionPagination,
} from "../../components/extraction/display";
import { ActionForm } from "../../components/extraction/ActionForm";
export const dynamic = "force-dynamic";
export default async function RunsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  try {
    const source = getExtractionSource(),
      query = pageQuery(await searchParams);
    const [page, permissions] = await Promise.all([
      source.read("runs", guards.runs, query),
      source.read("permissions", guards.permissions),
    ]);
    return (
      <ExtractionShell title="Extraction runs" mode={source.mode}>
        <p>Runs retain their original evidence, corpus, cutoff and workflow pins.</p>
        {!page.data.items.length ? (
          <p>No runs on this page.</p>
        ) : (
          <table>
            <caption>Run history</caption>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Cutoff</th>
                <th>Provider</th>
                <th>Cost USD</th>
              </tr>
            </thead>
            <tbody>
              {page.data.items.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link href={`/extraction-runs/${run.id}`}>{run.id}</Link>
                  </td>
                  <td>{run.status}</td>
                  <td>{run.as_of}</td>
                  <td>{run.provider}</td>
                  <td>{run.usage.cost_usd}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <ExtractionPagination
          path="/extraction-runs"
          query={Object.fromEntries(query)}
          page={page.data}
        />
        <ActionForm
          action="create"
          path="runs"
          permitted={permissions.data.allowed_actions.includes("create")}
        />
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Extraction runs">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}
