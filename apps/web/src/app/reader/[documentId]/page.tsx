import Link from "next/link";
import { PageNavigation } from "../../../components/PageNavigation";
import { notFound } from "next/navigation";

import { EvidenceFailureState } from "../../../components/EvidenceFailureState";
import { EvidenceReader } from "../../../components/EvidenceReader";
import { EvidenceApiError } from "../../../lib/data/http-source";
import { evidenceFailureState } from "../../../lib/data/failure-state";
import { getEvidenceSource } from "../../../lib/data/server";
import { loadReaderData } from "../../../lib/reader-loader";

export const dynamic = "force-dynamic";

export default async function ReaderPage({
  params,
  searchParams,
}: {
  params: Promise<{ documentId: string }>;
  searchParams?: Promise<{
    span?: string | string[];
    related?: string;
    sibling_cursor?: string;
    sibling_order?: "asc" | "desc";
    document_version_id?: string;
    as_of?: string;
    corpus_version_id?: string;
  }>;
}) {
  const { documentId } = await params;
  const search = (await searchParams) ?? {};
  const { span } = search;
  const initialSpanId = Array.isArray(span) ? span[0] : span;
  let result;
  try {
    result = await loadReaderData(getEvidenceSource(), documentId, {
      includeSiblings: search.related === "1",
      ...(search.related === "1"
        ? {
            siblingLimit: 10,
            siblingCursor: search.sibling_cursor,
            siblingOrder: search.sibling_order ?? "asc",
          }
        : {}),
      documentVersionId: search.document_version_id,
      asOf: search.as_of,
      corpusVersionId: search.corpus_version_id,
    });
  } catch (error) {
    const kind = evidenceFailureState(error);
    if (error instanceof EvidenceApiError && error.status === 413) {
      const meta = await getEvidenceSource()
        .getDocument(error.resourceDocumentId ?? documentId, { asOf: search.as_of })
        .catch(() => null);
      return (
        <>
          <EvidenceFailureState kind="too_large" />
          {search.related === "1" && (
            <p className="page-main">
              <Link
                href={`/reader/${encodeURIComponent(documentId)}?${new URLSearchParams({ ...(search.as_of ? { as_of: search.as_of } : {}), ...(search.document_version_id ? { document_version_id: search.document_version_id } : {}), ...(search.corpus_version_id !== undefined ? { corpus_version_id: search.corpus_version_id } : {}), ...(initialSpanId ? { span: initialSpanId } : {}) })}`}
              >
                Open target filing without related history
              </Link>
            </p>
          )}
          {meta && /^https?:\/\//i.test(meta.source_url) && (
            <p className="page-main">
              <a href={meta.source_url}>Open original filing</a>
            </p>
          )}
        </>
      );
    }
    if (kind) return <EvidenceFailureState kind={kind} />;
    throw error;
  }
  if (result.kind === "not_found") notFound();

  const { data } = result;
  const historyParams = {
    related: "1",
    document_version_id: data.documentVersionId,
    as_of: data.scope.as_of,
    corpus_version_id: data.scope.corpus_version_id ?? "",
    ...(initialSpanId ? { span: initialSpanId } : {}),
  };
  return (
    <>
      <section className="page-main" aria-label="Related filing history">
        {data.siblingPage?.scope === "excluded" ? (
          <Link
            href={`/reader/${encodeURIComponent(documentId)}?${new URLSearchParams(historyParams)}`}
          >
            Load related filings
          </Link>
        ) : (
          <PageNavigation
            path={`/reader/${encodeURIComponent(documentId)}`}
            params={historyParams}
            nextCursor={data.siblingPage?.next_cursor ?? null}
            previousCursor={data.siblingPage?.previous_cursor ?? null}
            order={search.sibling_order ?? "asc"}
            cursorKey="sibling_cursor"
            orderKey="sibling_order"
            label="Related filing pages"
          />
        )}
        {data.siblingPage?.scope === "page" && (
          <p>
            {data.siblingPage.returned} related filings on this page.{" "}
            {data.scope.corpus_version_id
              ? "Corpus-pinned history."
              : "Browsing history; pages may change between requests."}
          </p>
        )}
        <ul>
          {data.documents
            .filter((doc) => doc.id !== documentId)
            .map((doc) => (
              <li key={doc.id}>
                <Link
                  href={`/reader/${encodeURIComponent(doc.id)}?${new URLSearchParams({ as_of: data.scope.as_of, document_version_id: data.documentVersionIdByDocumentId[doc.id]!, corpus_version_id: data.scope.corpus_version_id ?? "" })}`}
                >
                  {doc.form ?? "Filing"} — {doc.accession}
                </Link>
              </li>
            ))}
        </ul>
      </section>
      {/* No key={documentId}: EvidenceReader now keys its internal useReducer
    state by documentId (see lib/reader-state.ts) and resets on a prop
    change, so a remount is no longer needed to keep selection, outline
    focus, and notes from leaking across documents (issue #198). */}
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
        historyComplete={data.siblingPage?.complete ?? true}
        evidenceScope={data.scope}
        documentVersionIdByDocumentId={data.documentVersionIdByDocumentId}
      />
    </>
  );
}
