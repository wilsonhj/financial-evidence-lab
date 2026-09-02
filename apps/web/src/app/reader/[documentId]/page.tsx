import { notFound } from "next/navigation";

import { EvidenceFailureState } from "../../../components/EvidenceFailureState";
import { EvidenceReader } from "../../../components/EvidenceReader";
import { evidenceFailureState } from "../../../lib/data/failure-state";
import { getEvidenceSource } from "../../../lib/data/server";
import { loadReaderData } from "../../../lib/reader-loader";

export const dynamic = "force-dynamic";

export default async function ReaderPage({
  params,
  searchParams,
}: {
  params: Promise<{ documentId: string }>;
  searchParams?: Promise<{ span?: string | string[] }>;
}) {
  const { documentId } = await params;
  const { span } = (await searchParams) ?? {};
  const initialSpanId = Array.isArray(span) ? span[0] : span;
  let result;
  try {
    result = await loadReaderData(getEvidenceSource(), documentId);
  } catch (error) {
    const kind = evidenceFailureState(error);
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw error;
  }
  if (result.kind === "not_found") notFound();

  const { data } = result;
  return (
    // No key={documentId}: EvidenceReader now keys its internal useReducer
    // state by documentId (see lib/reader-state.ts) and resets on a prop
    // change, so a remount is no longer needed to keep selection, outline
    // focus, and notes from leaking across documents (issue #198).
    <EvidenceReader
      documentId={documentId}
      documents={data.documents}
      sections={data.sections}
      spans={data.spans}
      facts={data.facts}
      documentIdBySectionId={data.documentIdBySectionId}
      documentIdBySpanId={data.documentIdBySpanId}
      integrityFailures={data.integrityFailures}
      initialSpanId={initialSpanId}
    />
  );
}
