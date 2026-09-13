import Link from "next/link";
import { getExtractionSource } from "../../../../lib/extraction/source";
import { guards } from "../../../../lib/extraction/contracts";
import { pageQuery } from "../../../../lib/extraction/page-query";
import {
  ExtractionShell,
  ExtractionError,
  ExtractionPagination,
} from "../../../../components/extraction/display";
export const dynamic = "force-dynamic";
export default async function VersionsPage({
  params,
  searchParams,
}: {
  params: Promise<{ recordId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  try {
    const source = getExtractionSource(),
      { recordId } = await params,
      query = pageQuery(await searchParams);
    const { data: page } = await source.read(
      `approved/${recordId}/versions`,
      guards.versions,
      query,
    );
    return (
      <ExtractionShell title="Immutable approval history" mode={source.mode}>
        <Link href={`/approved-extractions/${recordId}`}>Current approved head and correction</Link>
        {!page.items.length ? (
          <p>No versions on this page.</p>
        ) : (
          <ul>
            {page.items.map((v) => (
              <li key={v.version_id}>
                <Link href={`/approved-extractions/${recordId}/versions/${v.version_id}`}>
                  Version {v.version}
                </Link>{" "}
                · {v.created_at} · {v.approval_reason}
              </li>
            ))}
          </ul>
        )}
        <ExtractionPagination
          path={`/approved-extractions/${recordId}/versions`}
          query={Object.fromEntries(query)}
          page={page}
        />
      </ExtractionShell>
    );
  } catch {
    return (
      <ExtractionShell title="Immutable approval history">
        <ExtractionError />
      </ExtractionShell>
    );
  }
}
