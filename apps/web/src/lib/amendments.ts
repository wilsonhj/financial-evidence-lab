import type { DocumentMeta } from "./contracts";

/** Amendment/restatement linkage between filings of one entity. */
export interface AmendmentLink {
  /** The directly superseded filing (may itself be an earlier amendment). */
  originalId: string;
  /** The amending filing (form ends in "/A"). */
  amendmentId: string;
}

export type AmendmentStatus =
  | { kind: "original" }
  /**
   * Superseded by the AUTHORITATIVE (latest-published) amendment in the
   * chain — earlier amendments are themselves superseded by later ones.
   */
  | { kind: "superseded"; byDocumentId: string }
  | { kind: "amendment"; amendsDocumentId: string };

function isAmendmentForm(form: string | undefined): boolean {
  return typeof form === "string" && form.endsWith("/A");
}

function baseForm(form: string | undefined): string | undefined {
  if (!form) return undefined;
  return isAmendmentForm(form) ? form.slice(0, -2) : form;
}

/**
 * `published_at` compared as an instant: the contract allows any RFC 3339
 * offset, so raw string comparison would misorder e.g. "…T23:05:00+02:00"
 * (21:05Z) after "…T22:00:00Z".
 */
function publishedEpoch(doc: DocumentMeta): number {
  return Date.parse(doc.published_at);
}

/**
 * Period-matching rule (documented, deliberate): two filings cover the same
 * reporting period ONLY when BOTH period_start and BOTH period_end are
 * present and equal. A document missing either period field never matches —
 * undefined === undefined is NOT a match. The frozen DocumentMeta carries no
 * explicit amends-linkage pointer and accession numbers are assigned per
 * submission (no shared lineage root exists to fall back on), so period-less
 * documents are simply never cross-linked; when the contract grows an
 * explicit amends pointer this rule should defer to it.
 */
function periodsMatch(a: DocumentMeta, b: DocumentMeta): boolean {
  if (!a.period_start || !a.period_end || !b.period_start || !b.period_end) return false;
  return a.period_start === b.period_start && a.period_end === b.period_end;
}

/**
 * Links each amendment (form ending in "/A") to the filing it directly
 * supersedes: same entity, same fully-specified reporting period, same base
 * form, published at or before the amendment. Candidates INCLUDE earlier
 * amendments — an Amendment No. 2 supersedes Amendment No. 1, not the
 * original — and the latest-published candidate wins (epoch comparison, id
 * tie-break). Amendment-vs-amendment ties at the same instant require a
 * strictly earlier candidate so two simultaneous amendments can never link
 * to each other cyclically.
 */
export function linkAmendments(documents: readonly DocumentMeta[]): AmendmentLink[] {
  const links: AmendmentLink[] = [];
  for (const amendment of documents) {
    if (!isAmendmentForm(amendment.form)) continue;
    const amendmentEpoch = publishedEpoch(amendment);
    const candidates = documents
      .filter((doc) => {
        if (doc.id === amendment.id) return false;
        if (doc.entity_id !== amendment.entity_id) return false;
        if (baseForm(doc.form) !== baseForm(amendment.form)) return false;
        if (!periodsMatch(doc, amendment)) return false;
        const epoch = publishedEpoch(doc);
        if (Number.isNaN(epoch) || Number.isNaN(amendmentEpoch)) return false;
        // An originating non-amendment may share the amendment's timestamp;
        // a sibling amendment must be strictly earlier (no mutual links).
        return isAmendmentForm(doc.form) ? epoch < amendmentEpoch : epoch <= amendmentEpoch;
      })
      .sort((a, b) => publishedEpoch(a) - publishedEpoch(b) || a.id.localeCompare(b.id));
    const original = candidates[candidates.length - 1];
    if (original) {
      links.push({ originalId: original.id, amendmentId: amendment.id });
    }
  }
  return links;
}

/**
 * Amendment status of one document given the derived links. A document that
 * is superseded reports the TERMINAL amendment of its chain (the latest one),
 * so the superseded banner always points at the authoritative filing; a
 * superseded early amendment therefore reads as superseded, not as an
 * amendment.
 */
export function amendmentStatusFor(
  documentId: string,
  links: readonly AmendmentLink[],
): AmendmentStatus {
  const supersededBy = new Map(links.map((link) => [link.originalId, link.amendmentId]));
  if (supersededBy.has(documentId)) {
    let current = supersededBy.get(documentId)!;
    const visited = new Set<string>([documentId]);
    while (supersededBy.has(current) && !visited.has(current)) {
      visited.add(current);
      current = supersededBy.get(current)!;
    }
    return { kind: "superseded", byDocumentId: current };
  }
  const link = links.find((candidate) => candidate.amendmentId === documentId);
  if (link) {
    return { kind: "amendment", amendsDocumentId: link.originalId };
  }
  return { kind: "original" };
}
