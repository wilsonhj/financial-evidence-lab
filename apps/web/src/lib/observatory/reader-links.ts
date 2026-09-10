import type { EvidenceSource, EvidenceScope } from "../data/evidence-source";
import { EvidenceContractError } from "../data/http-source";

/** Resolve only evidence versions present in this trace, scoped to its immutable plan. */
export async function buildDocumentIdByVersionId(
  source: EvidenceSource,
  versionIds: readonly string[],
  scope: EvidenceScope,
): Promise<Record<string, string>> {
  const ids = [...new Set(versionIds)];
  const map: Record<string, string> = {};
  for (let offset = 0; offset < ids.length; offset += 200) {
    const batch = ids.slice(offset, offset + 200);
    for (const reference of await source.resolveDocumentVersions(batch, scope)) {
      if (!batch.includes(reference.document_version_id) || map[reference.document_version_id]) {
        throw new EvidenceContractError("unexpected or duplicate resolved version");
      }
      map[reference.document_version_id] = reference.document_id;
    }
  }
  return map;
}
