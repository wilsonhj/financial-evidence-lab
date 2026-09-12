import { cursor } from "./contracts";
export function pageQuery(
  values: Record<string, string | string[] | undefined> = {},
): URLSearchParams {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    // A tracking tag, a framework-appended key or a leftover param from another
    // view is ignored. Only the params this view actually reads are validated,
    // so one stray key cannot present itself as a configuration or access error.
    if (!["cursor", "limit", "state", "run_id", "status"].includes(key)) continue;
    // An empty control — the queue's "All states" — means no filter, not an error.
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) throw new Error("Invalid page query");
    if (key === "cursor" && !cursor(value)) throw new Error("Invalid cursor");
    query.set(key, value);
  }
  if (!query.has("limit") && !query.has("cursor")) query.set("limit", "50");
  return query;
}
