/**
 * Action-failure slugs written by server actions via observatoryFailureState
 * (plus validation → invalid_scope). Only these may be reflected from ?error=;
 * any other searchParam value is ignored rather than rendered verbatim.
 */
export const KNOWN_OBSERVATORY_ERRORS: ReadonlySet<string> = new Set([
  "authentication",
  "forbidden",
  "conflict",
  "invalid_scope",
  "unavailable",
  "integrity",
]);

/** Returns the slug when it is allowlisted; otherwise undefined (drop injected text). */
export function sanitizeObservatoryError(error: string | undefined): string | undefined {
  if (!error) return undefined;
  return KNOWN_OBSERVATORY_ERRORS.has(error) ? error : undefined;
}
