import { notFound } from "next/navigation";

import { EvidenceReader } from "../../../components/EvidenceReader";
import { evidenceSource } from "../../../lib/data";
import { formatPeriodRange } from "../../../lib/document-display";
import { loadReaderData } from "../../../lib/reader-loader";

export async function generateStaticParams() {
  const documents = await evidenceSource.listDocuments();
  return documents.map((doc) => ({ documentId: doc.id }));
}

export default async function ReaderPage({ params }: { params: Promise<{ documentId: string }> }) {
  const { documentId } = await params;
  // Failures other than "document does not exist" (e.g. EvidenceApiError from
  // the HTTP source) intentionally propagate to error.tsx — they must surface
  // as a real error state, never as a 404.
  const result = await loadReaderData(evidenceSource, documentId);
  if (result.kind === "not_found") notFound();

  if (result.kind === "details_unavailable") {
    const { document } = result;
    return (
      <main className="page-main" aria-labelledby="reader-unavailable-heading">
        <h2 id="reader-unavailable-heading">
          {document.form ?? "Filing"} — {document.accession}
        </h2>
        <p style={{ color: "var(--color-muted)" }}>
          Period {formatPeriodRange(document)} · Published {document.published_at.slice(0, 10)}
        </p>
        <p role="status">
          Evidence details (sections, source spans, and extracted facts) are not yet available from
          this data source.
        </p>
      </main>
    );
  }

  const { data } = result;
  return (
    // key={documentId}: navigating between filings must remount the reader so
    // selection, outline focus, and notes never leak across documents.
    <EvidenceReader
      key={documentId}
      documentId={documentId}
      documents={data.documents}
      sections={data.sections}
      spans={data.spans}
      facts={data.facts}
      documentIdBySectionId={data.documentIdBySectionId}
      documentIdBySpanId={data.documentIdBySpanId}
      integrityFailures={data.integrityFailures}
    />
  );
}
