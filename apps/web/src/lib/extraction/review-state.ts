import { guards, type Proposal, type Review, type Conflict } from "./contracts";

export type PendingRequest = {
  path: string;
  method: string;
  body: string;
  etag: string | null;
  key: string;
};
export function prepareRequest(
  path: string,
  method: string,
  body: string,
  etag: string | null,
  previous?: PendingRequest,
): PendingRequest {
  if (
    previous &&
    previous.path === path &&
    previous.method === method &&
    previous.body === body &&
    previous.etag === etag
  )
    return previous;
  return { path, method, body, etag, key: crypto.randomUUID() };
}
/** User-entered replacement JSON remains raw inside the body; never parse candidate fields. */
export function buildReview(
  selected: Proposal[],
  action: Review["action"],
  reason: string,
  patchText: string,
  conflicts: Conflict[],
  winnerIds: string[],
): string {
  if (
    !selected.length ||
    selected.length > 100 ||
    new Set(selected.map((p) => p.id)).size !== selected.length
  )
    throw new Error("Select 1–100 proposals");
  const selectedIds = selected.map((p) => p.id);
  const requiredGroups = new Set(selected.flatMap((p) => p.conflict_ids));
  if ([...requiredGroups].some((id) => !conflicts.some((c) => c.id === id)))
    throw new Error("Load complete conflict membership before reviewing");
  if (winnerIds.some((id) => !selectedIds.includes(id)))
    throw new Error("Winners must be explicitly selected proposals");
  const base = {
    action,
    extraction_ids: selectedIds,
    expected_versions: Object.fromEntries(selected.map((p) => [p.id, p.version])),
    reason,
    ...(conflicts.length
      ? {
          conflict_resolution: conflicts
            .filter((c) => requiredGroups.has(c.id) && c.status === "open")
            .map((c) => ({
              conflict_id: c.id,
              expected_etag: c.etag,
              member_versions: c.member_versions,
              selected_winner_ids: winnerIds.filter((id) => Object.hasOwn(c.member_versions, id)),
              reason,
            })),
        }
      : {}),
  };
  if ("conflict_resolution" in base && base.conflict_resolution?.length === 0)
    delete base.conflict_resolution;
  let body = JSON.stringify(base);
  if (action === "edit" || action === "merge") body = `${body.slice(0, -1)},"patch":${patchText}}`;
  const parsed: unknown = JSON.parse(body);
  if (!guards.review(parsed)) throw new Error("Supply a complete valid review command and reason");
  if (
    parsed.action === "edit" &&
    (parsed.patch.length !== selected.length ||
      new Set(parsed.patch.map((p) => p.extraction_id)).size !== selected.length ||
      parsed.patch.some((p) => !selectedIds.includes(p.extraction_id)))
  )
    throw new Error("Provide one full replacement for every selected proposal");
  if (parsed.action === "merge" && !selectedIds.includes(parsed.patch.payload_source_id))
    throw new Error("Select the merge payload source explicitly");
  return body;
}
export async function sendPrepared(
  pending: PendingRequest,
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  return fetcher(`/api/extraction/${pending.path}`, {
    method: pending.method,
    cache: "no-store",
    headers: {
      "idempotency-key": pending.key,
      ...(pending.etag ? { "if-match": pending.etag } : {}),
      ...(pending.body ? { "content-type": "application/json" } : {}),
    },
    ...(pending.body ? { body: pending.body } : {}),
  });
}
export const statusMessage = (status: number) =>
  status === 412
    ? "The reviewed version changed. Your draft is preserved. Refresh the comparison, then intentionally resubmit."
    : status === 409
      ? "This action conflicts with the current state. Review the current records before proceeding."
      : status === 413
        ? "This request or its evidence exceeds the supported limit. No partial action was applied."
        : status === 403
          ? "Your current permissions do not allow this action."
          : status === 422
            ? "Validation blocked this action. Check the full replacement, evidence and conflict decisions."
            : `The service could not complete the action (HTTP ${status}).`;
