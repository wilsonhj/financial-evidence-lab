import { guards, uuid, cursor, object, type Guard } from "./contracts";

export type Route = {
  upstream: string;
  output: Guard<unknown>;
  input?: Guard<unknown>;
  etag?: boolean;
  query?: string[];
  stream?: boolean;
  id?: string;
  workspace?: string;
  version?: string;
  record?: string;
};
const paging = ["limit", "cursor"];
/** The browser selects a named local resource, never an upstream URL. */
export function resolveRoute(path: string, method: string, workspace: string): Route | undefined {
  const parts = path.split("/");
  const [resource, id, action, version] = parts;
  if (
    parts.length > 4 ||
    (id !== undefined && !uuid(id)) ||
    (version !== undefined && !uuid(version))
  )
    return;
  if (method === "GET") {
    if (parts.length === 1) {
      if (resource === "permissions")
        return {
          upstream: `/v1/workspaces/${workspace}/extraction-permissions`,
          output: guards.permissions,
          workspace,
        };
      if (resource === "runs")
        return {
          upstream: `/v1/workspaces/${workspace}/extraction-runs`,
          output: guards.runs,
          query: paging,
          workspace,
        };
      if (resource === "proposals")
        return {
          upstream: `/v1/workspaces/${workspace}/extractions`,
          output: guards.proposals,
          query: [...paging, "state"],
        };
      if (resource === "conflicts")
        return {
          upstream: `/v1/workspaces/${workspace}/extraction-conflicts`,
          output: guards.conflicts,
          query: [...paging, "status"],
        };
    }
    if (id && parts.length === 2) {
      if (resource === "runs")
        return { upstream: `/v1/extraction-runs/${id}`, output: guards.run, etag: true, id };
      if (resource === "proposals")
        return { upstream: `/v1/extractions/${id}`, output: guards.proposal, etag: true, id };
      if (resource === "conflicts")
        return {
          upstream: `/v1/extraction-conflicts/${id}`,
          output: guards.conflict,
          etag: true,
          id,
        };
      if (resource === "approved")
        return {
          upstream: `/v1/approved-extractions/${id}`,
          output: guards.approved,
          etag: true,
          id,
        };
    }
    if (id && resource === "runs" && parts.length === 3) {
      if (action === "steps")
        return { upstream: `/v1/extraction-runs/${id}/steps`, output: guards.steps, query: paging };
      if (action === "event-history")
        return {
          upstream: `/v1/extraction-runs/${id}/event-history`,
          output: guards.events,
          query: paging,
          id,
        };
      if (action === "events")
        return {
          upstream: `/v1/extraction-runs/${id}/events`,
          output: guards.event,
          stream: true,
          id,
        };
    }
    if (resource === "approved" && id && action === "versions") {
      if (version)
        return {
          upstream: `/v1/approved-extractions/${id}/versions/${version}`,
          version,
          output: guards.approved,
          etag: true,
          id,
        };
      return {
        upstream: `/v1/approved-extractions/${id}/versions`,
        output: guards.versions,
        query: paging,
        record: id,
      };
    }
  }
  if (method === "POST") {
    if (path === "runs")
      return {
        upstream: `/v1/workspaces/${workspace}/extraction-runs`,
        input: guards.create,
        output: guards.run,
        etag: true,
        workspace,
      };
    if (path === "review")
      return { upstream: "/v1/extractions/review", input: guards.review, output: guards.result };
    if (parts.length === 3 && resource === "runs" && action === "rerun")
      return {
        upstream: `/v1/extraction-runs/${id}/rerun`,
        input: guards.rerun,
        output: guards.run,
        etag: true,
      };
    if (parts.length === 3 && resource === "approved" && action === "corrections")
      return {
        upstream: `/v1/approved-extractions/${id}/corrections`,
        input: guards.correction,
        output: guards.approved,
        etag: true,
        id,
      };
  }
  if (method === "DELETE" && resource === "runs" && id && parts.length === 2)
    return { upstream: `/v1/extraction-runs/${id}`, output: guards.run, etag: true, id };
}
export function queryFor(route: Route, params: URLSearchParams): string {
  for (const [key, value] of params) {
    if (!route.query?.includes(key) || params.getAll(key).length !== 1)
      throw new Error("Invalid query");
    if (key === "cursor" && !cursor(value)) throw new Error("Invalid cursor");
    if (key === "limit" && (!/^[1-9]\d{0,2}$/.test(value) || Number(value) > 200))
      throw new Error("Invalid limit");
    if (
      key === "state" &&
      !["proposed", "needs_review", "accepted", "rejected", "superseded"].includes(value)
    )
      throw new Error("Invalid state");
    if (key === "status" && !["open", "resolved", "superseded"].includes(value))
      throw new Error("Invalid status");
  }
  return params.size ? `?${params}` : "";
}
const sameId = (value: unknown, expected: string) =>
  uuid(value) && value.toLowerCase() === expected.toLowerCase();
export function matchesResource(
  route: Route,
  data: unknown,
  query = new URLSearchParams(),
): boolean {
  if (!object(data)) return false;
  if (route.id && !sameId(data.id ?? data.record_id ?? data.run_id, route.id)) return false;
  if (route.version && !sameId(data.version_id, route.version)) return false;
  if (
    route.workspace &&
    data.workspace_id !== undefined &&
    !sameId(data.workspace_id, route.workspace)
  )
    return false;
  if (Array.isArray(data.items)) {
    if (query.has("limit") && data.limit !== Number(query.get("limit"))) return false;
    if (
      query.has("cursor") &&
      [data.next_cursor, data.previous_cursor].includes(query.get("cursor"))
    )
      return false;
    const ids = new Set<string>();
    for (const item of data.items) {
      if (!object(item)) return false;
      if (route.workspace && !sameId(item.workspace_id, route.workspace)) return false;
      if (route.record && !sameId(item.record_id, route.record)) return false;
      for (const filter of ["state", "status"])
        if (query.has(filter) && item[filter] !== query.get(filter)) return false;
      const id = String(item.version_id ?? item.id).toLowerCase();
      if (ids.has(id)) return false;
      ids.add(id);
    }
  }
  return true;
}
