import Link from "next/link";

import { EvidenceFailureState } from "../components/EvidenceFailureState";
import { PageNavigation } from "../components/PageNavigation";
import { evidenceFailureState } from "../lib/data/failure-state";
import { getEvidenceSource } from "../lib/data/server";
import { formatPeriodRange } from "../lib/document-display";

export const dynamic = "force-dynamic";

export default async function DocumentListPage({
  searchParams,
}: {
  searchParams?: Promise<{ entity?: string; cursor?: string; order?: "asc" | "desc" }>;
}) {
  const search = (await searchParams) ?? {};
  let page;
  let entityIds: readonly string[];
  let entityId: string;
  try {
    const source = getEvidenceSource();
    entityIds = source.entityIds;
    entityId = search.entity ?? entityIds[0] ?? "";
    page = await source.listDocuments(entityId, {
      limit: 50,
      cursor: search.cursor,
      order: search.order ?? "asc",
    });
  } catch (error) {
    const kind = evidenceFailureState(error);
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw error;
  }
  const documents = page.items;

  return (
    <main id="main-content" tabIndex={-1} className="page-main" aria-labelledby="documents-heading">
      <h2 id="documents-heading">Filings</h2>
      <p>Select a filing to open its version-pinned evidence snapshot.</p>
      <form action="/">
        <label htmlFor="filing-entity">Entity</label>{" "}
        <select id="filing-entity" name="entity" defaultValue={entityId}>
          {entityIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>{" "}
        <button type="submit">Show filings</button>
      </form>
      <PageNavigation
        path="/"
        params={{ entity: entityId }}
        nextCursor={page.nextCursor}
        previousCursor={page.previousCursor}
        order={search.order ?? "asc"}
        label="Filing pages"
      />
      <p>Showing {documents.length} filings. Amendment history is not fully loaded.</p>
      <table className="doc-table">
        <thead>
          <tr>
            <th scope="col">Form</th>
            <th scope="col">Accession</th>
            <th scope="col">Period</th>
            <th scope="col">Published</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => {
            return (
              <tr key={doc.id}>
                <td>
                  <Link href={`/reader/${doc.id}`}>{doc.form ?? "Filing"}</Link>
                </td>
                <td>
                  {doc.accession}
                  {/^https?:\/\//i.test(doc.source_url) && (
                    <>
                      {" "}
                      · <a href={doc.source_url}>Original filing</a>
                    </>
                  )}
                </td>
                <td>{formatPeriodRange(doc)}</td>
                <td>{doc.published_at.slice(0, 10)}</td>
                <td>
                  <span className="badge">
                    {doc.form?.endsWith("/A") ? "Amendment / restatement" : "History not loaded"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </main>
  );
}
