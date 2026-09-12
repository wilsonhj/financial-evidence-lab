import Link from "next/link";
import { getExtractionSource } from "../../lib/extraction/source";
import { guards } from "../../lib/extraction/contracts";
import { pageQuery } from "../../lib/extraction/page-query";
import {
  ExtractionShell,
  ExtractionError,
  ExtractionPagination,
} from "../../components/extraction/display";
import { ReviewQueue } from "../../components/extraction/ReviewQueue";
export const dynamic = "force-dynamic";
export default async function ExtractionsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  try {
    const source = getExtractionSource(),
      query = pageQuery(await searchParams);
    const [page, permissions] = await Promise.all([
      source.read("proposals", guards.proposals, query),
      source.read("permissions", guards.permissions),
    ]);
    return (
      <ExtractionShell title="Extraction review" mode={source.mode}>
        <p>
          Inspect evidence and deterministic validation before approving an immutable financial
          record.
        </p>
        <form method="get">
          <label htmlFor="queue-state">State</label>
          <select name="state" id="queue-state" defaultValue={query.get("state") ?? "needs_review"}>
            {["proposed", "needs_review", "accepted", "rejected", "superseded"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <button type="submit">Filter queue</button>
        </form>
        <ReviewQueue
          key={query.toString()}
          proposals={page.data.items}
          permissions={permissions.data}
        />
        <ExtractionPagination
          path="/extractions"
          query={Object.fromEntries(query)}
          page={page.data}
        />
        {source.mode === "fixture" && (
          <p>
            <Link href="/approved-extractions/eeeeeeee-0000-4000-8000-000000000007">
              Inspect synthetic immutable approval history
            </Link>
          </p>
        )}
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Extraction review">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}
