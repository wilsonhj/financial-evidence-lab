import Link from "next/link";
import type { Schemas } from "../../lib/extraction/contracts";
import { getEvidenceSource } from "../../lib/data/server";

export async function SourceLinks({
  evidence,
  sources,
}: {
  evidence: Schemas["EvidenceEdge"][];
  sources: { run_id: string; as_of: string; corpus_version_id?: string }[] | null;
}) {
  if (!sources)
    return (
      <section>
        <h2>Historical source context</h2>
        <p>
          Unknown: this historical version has no recorded validation context. No current cutoff was
          substituted.
        </p>
        <ul>
          {evidence.map((e, i) => (
            <li key={i}>
              Span {e.source_span_id} · Parsed version {e.document_version_id}
            </li>
          ))}
        </ul>
      </section>
    );
  let references: Awaited<
    ReturnType<ReturnType<typeof getEvidenceSource>["resolveDocumentVersions"]>
  > = [];
  const source = sources.length === 1 ? sources[0] : undefined;
  if (source && evidence.length) {
    try {
      references = await getEvidenceSource().resolveDocumentVersions(
        [...new Set(evidence.map((e) => e.document_version_id))],
        { asOf: source.as_of, corpusVersionId: source.corpus_version_id ?? null },
      );
    } catch {
      /* Pins remain visible; unavailable evidence never gains an invented link. */
    }
  }
  return (
    <section aria-label="Frozen evidence provenance">
      <h2>Source context</h2>
      <ul>
        {sources.map((s) => (
          <li key={s.run_id}>
            <Link href={`/extraction-runs/${s.run_id}`}>Source run {s.run_id}</Link> · Cutoff{" "}
            {s.as_of} · Corpus {s.corpus_version_id ?? "No corpus pin recorded"}
          </li>
        ))}
      </ul>
      {sources.length > 1 && (
        <p>
          This version combines multiple source contexts. Follow the immutable source runs to
          inspect their respective cutoffs and corpora.
        </p>
      )}
      {!evidence.length && <p>No evidence edges recorded.</p>}
      <ul>
        {evidence.map((edge, index) => {
          const reference = references.find(
            (r) => r.document_version_id === edge.document_version_id,
          );
          const query =
            source &&
            new URLSearchParams({
              as_of: source.as_of,
              corpus_version_id: source.corpus_version_id ?? "",
              document_version_id: edge.document_version_id,
              span: edge.source_span_id,
            });
          return (
            <li key={index}>
              {edge.role} · {edge.citation_status} ·{" "}
              {reference && query ? (
                <Link href={`/reader/${reference.document_id}?${query}`}>
                  Read evidence span {edge.source_span_id}
                </Link>
              ) : (
                <>
                  Span {edge.source_span_id} · Parsed version {edge.document_version_id}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
