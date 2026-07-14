import type { DocumentMeta } from "./contracts";

/**
 * Human-readable reporting-period range with an explicit fallback: the
 * contract makes period_start/period_end optional, so absent fields render as
 * "n/a" instead of the literal string "undefined".
 */
export function formatPeriodRange(doc: Pick<DocumentMeta, "period_start" | "period_end">): string {
  const { period_start: start, period_end: end } = doc;
  if (start && end) return `${start} to ${end}`;
  if (start) return `${start} to n/a`;
  if (end) return `n/a to ${end}`;
  return "n/a";
}
