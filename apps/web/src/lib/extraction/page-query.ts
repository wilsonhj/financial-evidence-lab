import { cursor } from "./contracts";
export function pageQuery(
  values: Record<string, string | string[] | undefined> = {},
): URLSearchParams {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (!value || Array.isArray(value) || !["cursor", "limit", "state", "status"].includes(key))
      throw new Error("Invalid page query");
    if (key === "cursor" && !cursor(value)) throw new Error("Invalid cursor");
    query.set(key, value);
  }
  if (!query.has("limit") && !query.has("cursor")) query.set("limit", "50");
  return query;
}
