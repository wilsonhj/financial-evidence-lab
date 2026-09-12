import "node:process";
import { fixtureStream } from "./fixture-stream";
import { fixturePage } from "../data/pagination";
import { fixtureAction } from "./fixture-actions";
import { MOCK_CORPUS_VERSION_ID } from "../observatory/fixtures/synthetic-trace";
import rawPayload from "@fel/contracts/fixtures/extraction-payload.json";
import { DOC_10Q_VERSION_ID, ENTITY_ID, fixtureSpans } from "../fixtures/synthetic-filing";
import {
  guards,
  type Run,
  type Proposal,
  type Approved,
  type Conflict,
  type Event,
  type Permissions,
} from "./contracts";

export const fixtureId = (n: number) => `eeeeeeee-0000-4000-8000-${n.toString().padStart(12, "0")}`;
export const FIXTURE_WORKSPACE = fixtureId(1);
export const FIXTURE_RUN = fixtureId(2);
export const FIXTURE_RECORD = fixtureId(7);
if (!guards.payload(rawPayload) || rawPayload.kind !== "kpi")
  throw new Error("Invalid committed extraction payload fixture");
const strictPayload = rawPayload;
const span = fixtureSpans.find((s) => s.span.document_version_id === DOC_10Q_VERSION_ID);
if (!span) throw new Error("Missing synthetic evidence span");
const evidence = [
  {
    source_span_id: span.id,
    document_version_id: DOC_10Q_VERSION_ID,
    role: "supports" as const,
    citation_status: "verified" as const,
  },
];
export function initialFixture() {
  const run: Run = {
    id: FIXTURE_RUN,
    workspace_id: FIXTURE_WORKSPACE,
    entity_id: ENTITY_ID,
    status: "waiting_review",
    modes: ["kpi"],
    as_of: "2026-07-01T00:00:00Z",
    corpus_version_id: MOCK_CORPUS_VERSION_ID,
    ontology_version: "saas-metrics/v1",
    workflow_version: "extraction-workflow/v3",
    provider: "mock",
    model: "synthetic-fixture",
    limits: { max_calls: 10, max_cost_usd: "2.00" },
    usage: { calls: 1, input_tokens: 40, output_tokens: 20, cost_usd: "0" },
    version: 1,
    created_at: "2026-07-01T00:00:00Z",
    cancel_requested_at: null,
  };
  const first: Proposal = {
    id: fixtureId(3),
    run_id: run.id,
    kind: "kpi",
    metric_id: "arr",
    payload: strictPayload,
    evidence,
    record_confidence: null,
    field_confidences: {},
    validations: [{ code: "fixture_validation", status: "pass" }],
    state: "needs_review",
    review_priority: "normal",
    version: 1,
    conflict_ids: [fixtureId(6)],
  };
  const second: Proposal = {
    ...first,
    id: fixtureId(4),
    payload: { ...strictPayload, raw_value: "$101 million", value: "101" },
  };
  const invalid: Proposal = {
    ...first,
    id: fixtureId(5),
    payload: {
      schema_version: "extraction-candidate-fields/v1",
      fields: {
        value: "9007199254740993",
        dimensions: "null",
        qualifiers: '{"fraction": 0.1}',
        raw_value: '"<script>alert(1)</script>"',
      },
    },
    evidence: [],
    validations: [{ code: "numeric_invalid", status: "fail" }],
    review_priority: "high",
    conflict_ids: [],
  };
  const conflict: Conflict = {
    id: fixtureId(6),
    conflict_key: `sha256:${"a".repeat(64)}`,
    occurrence_run_id: run.id,
    status: "open",
    reason_codes: ["value_disagreement"],
    member_versions: { [first.id]: 1, [second.id]: 1 },
    etag: '"fixture-group-1"',
    resolution: null,
  };
  const approved: Approved = {
    record_id: FIXTURE_RECORD,
    version_id: fixtureId(8),
    version: 1,
    parent_version_id: null,
    kind: "kpi",
    metric_id: "arr",
    payload: strictPayload,
    evidence,
    evidence_manifest_hash: `sha256:${"b".repeat(64)}`,
    ontology_version: "saas-metrics/v1",
    approved_by: fixtureId(9),
    created_at: run.created_at,
    approval_reason: "Synthetic historical approval",
    normalizer_version: "normalize/v2",
    validator_version: "validate/v3",
    validation_context: null,
  };
  const permissions: Permissions = {
    workspace_id: FIXTURE_WORKSPACE,
    allowed_actions: ["create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"],
  };
  const events: Event[] = [
    {
      schema_version: "extraction-event/v1",
      id: 1,
      run_id: run.id,
      type: "review_waiting",
      occurred_at: run.created_at,
      payload: { proposals: 3 },
    },
  ];
  return {
    runs: [run],
    proposals: [first, second, invalid],
    conflicts: [conflict],
    versions: [approved],
    permissions,
    events,
  };
}
export type FixtureState = ReturnType<typeof initialFixture>;
class FixturePage extends Error {}
/** The active filters belong in the scope so a cursor cannot outlive them. */
const scopeFor = (base: string, query: URLSearchParams, keys: string[]) =>
  [base, ...keys.map((key) => `${key}=${query.get(key) ?? ""}`)].join("|");
/** Reuses the reader surface's scope-bound cursor so one token format exists. */
function page<T>(items: T[], query: URLSearchParams, scope: string) {
  const limit = query.get("limit"),
    cursor = query.get("cursor");
  const result = fixturePage(
    items,
    {
      ...(limit === null ? {} : { limit: Number(limit) }),
      ...(cursor === null ? {} : { cursor }),
    },
    scope,
    FixturePage,
  );
  return {
    items: result.items,
    limit: result.limit,
    next_cursor: result.nextCursor,
    previous_cursor: result.previousCursor,
  };
}
const json = (value: unknown, tag?: string) =>
  Response.json(value, { headers: tag ? { etag: tag } : {} });
export const fixtureError = (status: number, code: string) =>
  Response.json(
    { error: { code, message: "Synthetic fixture request failed", request_id: "fixture" } },
    { status },
  );
/** Synthetic UI data only. This does not run financial validators or establish live acceptance. */
export function fixtureFetch(state: FixtureState): typeof fetch {
  return async (input, init) => {
    const url = new URL(String(input));
    const path = url.pathname,
      query = url.searchParams;
    const method = init?.method ?? "GET";
    if (method !== "GET") return fixtureAction(state, path, init ?? {});
    try {
      const workspace = `/v1/workspaces/${FIXTURE_WORKSPACE}`;
      if (path === `${workspace}/extraction-permissions`) return json(state.permissions);
      if (path === `${workspace}/extraction-runs`) return json(page(state.runs, query, "runs"));
      if (path === `${workspace}/extractions`)
        return json(
          page(
            state.proposals.filter(
              (p) =>
                (!query.has("run_id") || p.run_id === query.get("run_id")) &&
                (!query.has("state") || p.state === query.get("state")),
            ),
            query,
            scopeFor("proposals", query, ["state", "run_id"]),
          ),
        );
      if (path === `${workspace}/extraction-conflicts`)
        return json(
          page(
            state.conflicts.filter(
              (c) =>
                (!query.has("run_id") || c.occurrence_run_id === query.get("run_id")) &&
                (!query.has("status") || c.status === query.get("status")),
            ),
            query,
            scopeFor("conflicts", query, ["status", "run_id"]),
          ),
        );
      const [, , resource, id, action, versionId] = path.split("/");
      if (resource === "extraction-runs") {
        const run = state.runs.find((r) => r.id === id);
        if (!run) return fixtureError(404, "NOT_FOUND");
        if (!action) return json(run, `"fixture-run-${run.version}-${run.status}"`);
        if (action === "events")
          return fixtureStream(
            state,
            run.id,
            Number(new Headers(init?.headers).get("last-event-id") ?? 0),
            init?.signal,
          );
        if (action === "steps")
          return json(
            page(
              [
                {
                  id: fixtureId(10),
                  step_name: "validate",
                  attempt: 1,
                  status: "succeeded",
                  input_hash: "fixture-input",
                  output_hash: "fixture-output",
                  started_at: run.created_at,
                  finished_at: run.created_at,
                },
              ],
              query,
              "steps",
            ),
          );
        if (action === "event-history")
          return json({
            ...page(
              state.events.filter((e) => e.run_id === id),
              query,
              `events|run=${id}`,
            ),
            run_id: id,
          });
      }
      if (resource === "extractions") {
        const proposal = state.proposals.find((p) => p.id === id);
        if (proposal) return json(proposal, `"${proposal.version}"`);
      }
      if (resource === "extraction-conflicts") {
        const conflict = state.conflicts.find((c) => c.id === id);
        if (conflict) return json(conflict, conflict.etag);
      }
      if (resource === "approved-extractions") {
        const versions = state.versions
          .filter((v) => v.record_id === id)
          .sort((a, b) => b.version - a.version);
        if (action === "versions" && !versionId)
          return json(page(versions, query, `versions|record=${id}`));
        const approved = versionId ? versions.find((v) => v.version_id === versionId) : versions[0];
        if (approved) return json(approved, `"${approved.version}"`);
      }
      return fixtureError(404, "NOT_FOUND");
    } catch {
      return fixtureError(422, "VALIDATION_ERROR");
    }
  };
}
