import type { EvidenceSource } from "../data/evidence-source";

/**
 * Resolves document-version ids (which the trace carries on each candidate) to
 * the DocumentMeta ids the reader route is keyed by, so a candidate can deep
 * link to its exact evidence span. Built from the reader evidence source so it
 * works in both fixture and HTTP modes; versions that cannot be resolved are
 * simply absent and their candidate links are disabled rather than broken.
 */
export async function buildDocumentIdByVersionId(
  source: EvidenceSource,
): Promise<Record<string, string>> {
  const map: Record<string, string> = {};
  const documents = await source.listDocuments();
  for (const document of documents) {
    const reader = await source.getReader(document.id);
    if (!reader) continue;
    map[reader.document.document_version_id] = reader.document.meta.id;
    for (const sibling of reader.siblings) {
      map[sibling.document_version_id] = sibling.meta.id;
    }
  }
  return map;
}
