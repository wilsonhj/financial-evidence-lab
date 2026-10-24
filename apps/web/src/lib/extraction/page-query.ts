import { cursor } from "./contracts";
export function pageQuery(
  values: Record<string, string | string[] | undefined> = {},
): URLSearchParams {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    // The published queue contract refuses a run filter. Dropping it silently
    // would show an unfiltered queue under a URL that claims one.
    if (key === "run_id") throw new Error("Unsupported page filter");
    // A tracking tag or framework-appended key is not this view's to validate:
    // one stray key must not present itself as a configuration or access error.
    if (!["cursor", "limit", "state", "status"].includes(key)) continue;
    if (!value || Array.isArray(value)) throw new Error("Invalid page query");
    if (key === "cursor" && !cursor(value)) throw new Error("Invalid cursor");
    query.set(key, value);
  }
  if (!query.has("limit") && !query.has("cursor")) query.set("limit", "50");
  return query;
}
