import type { DocumentMeta } from "./contracts";

/** Amendment/restatement linkage between document versions of one entity. */
export interface AmendmentLink {
  /** The superseded original filing. */
  originalId: string;
  /** The amending filing (form ends in "/A"). */
  amendmentId: string;
}

export type AmendmentStatus =
  | { kind: "original" }
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
 * Links amendments to the filings they amend: same entity, same reporting
 * period, base form matching the amendment's form minus the "/A" suffix, and
 * the amendment filed after the original. DocumentMeta carries no explicit
 * "amends" pointer, so linkage is derived from the spec 10.3 temporal fields.
 */
export function linkAmendments(documents: readonly DocumentMeta[]): AmendmentLink[] {
  const links: AmendmentLink[] = [];
  for (const amendment of documents) {
    if (!isAmendmentForm(amendment.form)) continue;
    const candidates = documents
      .filter(
        (doc) =>
          doc.id !== amendment.id &&
          doc.entity_id === amendment.entity_id &&
          !isAmendmentForm(doc.form) &&
          baseForm(doc.form) === baseForm(amendment.form) &&
          doc.period_start === amendment.period_start &&
          doc.period_end === amendment.period_end &&
          doc.published_at <= amendment.published_at,
      )
      .sort((a, b) => a.published_at.localeCompare(b.published_at));
    const original = candidates[candidates.length - 1];
    if (original) {
      links.push({ originalId: original.id, amendmentId: amendment.id });
    }
  }
  return links;
}

/** Amendment status of one document given the derived links. */
export function amendmentStatusFor(
  documentId: string,
  links: readonly AmendmentLink[],
): AmendmentStatus {
  for (const link of links) {
    if (link.originalId === documentId) {
      return { kind: "superseded", byDocumentId: link.amendmentId };
    }
    if (link.amendmentId === documentId) {
      return { kind: "amendment", amendsDocumentId: link.originalId };
    }
  }
  return { kind: "original" };
}
