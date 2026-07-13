import Link from "next/link";

import { amendmentStatusFor, linkAmendments } from "../lib/amendments";
import { evidenceSource } from "../lib/data";
import { formatPeriodRange } from "../lib/document-display";

export default async function DocumentListPage() {
  const documents = await evidenceSource.listDocuments();
  const links = linkAmendments(documents);

  return (
    <main className="page-main" aria-labelledby="documents-heading">
      <h2 id="documents-heading">Filings</h2>
      <p>
        Select a filing to open it in the evidence reader. Data comes from the committed synthetic
        fixture until the ingestion API (M1-INGESTION) is available.
      </p>
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
            const status = amendmentStatusFor(doc.id, links);
            return (
              <tr key={doc.id}>
                <td>
                  <Link href={`/reader/${doc.id}`}>{doc.form ?? "Filing"}</Link>
                </td>
                <td>{doc.accession}</td>
                <td>{formatPeriodRange(doc)}</td>
                <td>{doc.published_at.slice(0, 10)}</td>
                <td>
                  {status.kind === "superseded" && (
                    <span className="badge badge-warning">
                      <span aria-hidden="true">&#9888;</span> Superseded by amendment
                    </span>
                  )}
                  {status.kind === "amendment" && (
                    <span className="badge badge-info">Amendment / restatement</span>
                  )}
                  {status.kind === "original" && <span className="badge">Current</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </main>
  );
}
